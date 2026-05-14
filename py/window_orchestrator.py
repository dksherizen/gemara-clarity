"""Window-based build orchestrator.

PRINCIPLE: Sugyot span amudim. Single-amud processing was producing artificial
sugya boundaries at amud breaks. The fix: process N consecutive amudim as one
unit (a "window"), let the segmentation pass identify true sugyot across that
window, then split the output JSONs per amud at the end.

WINDOW SIZE: 5 amudim. Big enough that most sugyot fit; small enough that the
total input stays in Qwen 27B's comfortable working set (~5k input tokens).
Adjacent windows do NOT overlap — each amud is processed exactly once. Sugyot
that cross a window boundary are still split, but that's rare; most sugyot
are within one window."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from llm import LMStudioClient
from passes.meforshim import enrich_steps
from passes.phrasemap import build_phrases_for_step
from passes.segment import segment_amud, SegmentResult
from passes.source_check import apply_source_checks
from passes.structure import skeleton_to_step, structure_sugya
from passes.teaching import polish_steps
from passes.translate import translate_all_steps
from schema import (
    CostBreakdown,
    DafAnalysis,
    DafSourceText,
    Phrase,
    Step,
    SugyaBoundary,
)
from sefaria import (
    DafSource,
    MeforeshWithText,
    fetch_daf_text,
    fetch_meforshim_by_anchor,
)

PIPELINE_VERSION = "py-window-1"
DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "public" / "data"
CHECKPOINT_DIR = DEFAULT_OUT_DIR / "_checkpoints"
WINDOW_SIZE = 5  # amudim per window


def _checkpoint_path(window_label: str) -> Path:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    return CHECKPOINT_DIR / f"{window_label}.checkpoint.json"


def _save_checkpoint(window_label: str, stage: str, payload: dict) -> None:
    """Save a partial-state checkpoint. Stage is one of:
    'segmented', 'structured', 'phrased', 'meforshim', 'polished'."""
    p = _checkpoint_path(window_label)
    payload = {"stage": stage, "saved_at": _now_iso(), **payload}
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _load_checkpoint(window_label: str) -> dict | None:
    p = _checkpoint_path(window_label)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _clear_checkpoint(window_label: str) -> None:
    p = _checkpoint_path(window_label)
    if p.exists():
        try:
            p.unlink()
        except Exception:
            pass


@dataclass
class AmudData:
    """One amud's source + meforshim, before the LLM passes run."""
    masechet: str
    daf: int
    amud: str  # "a" / "b"
    source: DafSource
    by_anchor: dict[str, list[MeforeshWithText]]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _log(start: float, msg: str) -> None:
    s = int(time.monotonic() - start)
    print(f"[{s // 60:d}m{s % 60:02d}s] {msg}", flush=True)


async def _fetch_one_amud(masechet: str, daf: int, amud: str) -> AmudData | None:
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            source = await fetch_daf_text(c, masechet, daf, amud)
        by_anchor = await fetch_meforshim_by_anchor(masechet, daf, amud)
        return AmudData(
            masechet=masechet, daf=daf, amud=amud,
            source=source, by_anchor=by_anchor,
        )
    except RuntimeError as e:
        if "No Hebrew source returned" in str(e):
            return None
        raise


async def _fetch_window(masechet: str, amud_pairs: list[tuple[int, str]]) -> list[AmudData]:
    out: list[AmudData] = []
    for daf, amud in amud_pairs:
        d = await _fetch_one_amud(masechet, daf, amud)
        if d is not None:
            out.append(d)
    return out


def _concat_window(window: list[AmudData]) -> tuple[DafSourceText, list[tuple[int, int, str]]]:
    """Concatenate the window's amudim into one combined source. Returns:
    - combined DafSourceText
    - per-amud (start_line, end_line, "{daf}{amud}") tuples that say where each
      amud sits in the combined line space.
    """
    hebrew: list[str] = []
    english: list[str] = []
    amud_ranges: list[tuple[int, int, str]] = []
    cursor = 1  # 1-indexed line numbers
    for a in window:
        start = cursor
        hebrew.extend(a.source.hebrew)
        english.extend(a.source.english)
        cursor = start + len(a.source.hebrew)
        end = cursor - 1
        amud_ranges.append((start, end, f"{a.daf}{a.amud}"))
    combined = DafSourceText(
        ref=f"{window[0].masechet} {window[0].daf}{window[0].amud}-{window[-1].daf}{window[-1].amud}",
        masechet=window[0].masechet,
        daf=window[0].daf,
        amud=window[0].amud,  # type: ignore[arg-type]
        hebrew=hebrew,
        english=english,
    )
    return combined, amud_ranges


def _aramaic_chunk(daf: DafSourceText, start_line: int, end_line: int) -> tuple[str, str]:
    he = " ".join(daf.hebrew[start_line - 1 : end_line])
    if not daf.english:
        return he, ""
    if len(daf.english) == len(daf.hebrew):
        en = " ".join(daf.english[start_line - 1 : end_line])
        return he, en
    full_en = " ".join(daf.english)
    en_words = full_en.split()
    n_he_total = sum(len(h.split()) for h in daf.hebrew) or 1
    n_he_before = sum(len(h.split()) for h in daf.hebrew[: start_line - 1])
    n_he_in_step = sum(len(h.split()) for h in daf.hebrew[start_line - 1 : end_line])
    start_frac = n_he_before / n_he_total
    end_frac = (n_he_before + n_he_in_step) / n_he_total
    en_start = int(start_frac * len(en_words))
    en_end = int(end_frac * len(en_words))
    return he, " ".join(en_words[en_start:en_end])


def _attach_phrases(
    daf: DafSourceText,
    steps: list[Step],
    step_line_ranges: list[tuple[int, int]],
) -> list[Step]:
    out: list[Step] = []
    for step, (s, e) in zip(steps, step_line_ranges, strict=True):
        ar, en = _aramaic_chunk(daf, s, e)
        if not ar.strip():
            out.append(step)
            continue
        out.append(step.model_copy(update={"phrases": build_phrases_for_step(ar, en)}))
    return out


def _which_amud(line: int, amud_ranges: list[tuple[int, int, str]]) -> str | None:
    for start, end, label in amud_ranges:
        if start <= line <= end:
            return label
    return None


def _split_to_amud_jsons(
    window: list[AmudData],
    combined: DafSourceText,
    amud_ranges: list[tuple[int, int, str]],
    sugyot: list[SugyaBoundary],
    steps: list[Step],
    step_line_ranges: list[tuple[int, int]],
    models_used: dict[str, str],
    seconds_by_pass: dict[str, float],
    main_topic: str,
    overview: str,
) -> list[tuple[str, DafAnalysis]]:
    """Split the window's combined output into per-amud DafAnalysis objects.

    Strategy: each step belongs to ONE amud (the amud containing its first line).
    A sugya that spans amudim shows up once per amud it touches; its
    `firstStepNumber` and `lastStepNumber` reflect only the steps inside that
    amud, and a custom marker tells the UI it continues into the next one."""
    # Build per-amud assignments.
    by_label: dict[str, dict] = {}
    for start, end, label in amud_ranges:
        # Find the AmudData that owns this label.
        amud_data = next(
            (a for a in window if f"{a.daf}{a.amud}" == label), None
        )
        if amud_data is None:
            continue
        by_label[label] = {
            "amud_data": amud_data,
            "start": start,
            "end": end,
            "steps": [],
            "step_line_ranges": [],
            "sugyot": [],
        }

    # Assign steps to the amud containing their first line.
    for step, rng in zip(steps, step_line_ranges, strict=True):
        s_line, e_line = rng
        owner_label = _which_amud(s_line, amud_ranges)
        if owner_label and owner_label in by_label:
            by_label[owner_label]["steps"].append(step)
            by_label[owner_label]["step_line_ranges"].append(rng)

    # Assign sugyot: a sugya gets emitted in EVERY amud it touches, with line
    # numbers RELATIVE to that amud.
    for sg in sugyot:
        for label, info in by_label.items():
            start, end = info["start"], info["end"]
            # Overlap?
            if sg.endLine < start or sg.startLine > end:
                continue
            local_start = max(sg.startLine, start) - start + 1
            local_end = min(sg.endLine, end) - start + 1
            crosses_before = sg.startLine < start
            crosses_after = sg.endLine > end
            topic = sg.topic
            gist = sg.gist
            if crosses_before:
                topic = f"(continues) {topic}"
            if crosses_after:
                gist = f"{gist} — discussion continues into next amud."
            info["sugyot"].append(
                sg.model_copy(
                    update={
                        "startLine": local_start,
                        "endLine": local_end,
                        "topic": topic,
                        "gist": gist,
                    }
                )
            )

    out_pairs: list[tuple[str, DafAnalysis]] = []
    for label, info in by_label.items():
        amud_data: AmudData = info["amud_data"]
        # Renumber steps 1..N within this amud.
        amud_steps: list[Step] = info["steps"]
        renumbered = [
            s.model_copy(update={"stepNumber": i + 1})
            for i, s in enumerate(amud_steps)
        ]
        # Renumber sugyot 1..M within this amud AND set firstStepNumber /
        # lastStepNumber to point at the RENUMBERED step IDs (1..N within
        # this amud) so the frontend's per-sugya step grouping works.
        amud_sugyot: list[SugyaBoundary] = info["sugyot"]
        step_line_ranges_amud: list[tuple[int, int]] = info["step_line_ranges"]
        # Each step's amud-local line range = window range minus amud start + 1.
        amud_start_in_window = info["start"]
        renumbered_sugyot: list[SugyaBoundary] = []
        for i, sg in enumerate(amud_sugyot):
            steps_in_this_sugya: list[int] = []
            for step_idx, (s_line, e_line) in enumerate(step_line_ranges_amud):
                local_start = s_line - amud_start_in_window + 1
                local_end = e_line - amud_start_in_window + 1
                # Overlap?
                if local_end < sg.startLine or local_start > sg.endLine:
                    continue
                steps_in_this_sugya.append(step_idx + 1)  # 1-indexed renumbered ID
            first_step = min(steps_in_this_sugya) if steps_in_this_sugya else None
            last_step = max(steps_in_this_sugya) if steps_in_this_sugya else None
            renumbered_sugyot.append(
                sg.model_copy(update={
                    "sugyaNumber": i + 1,
                    "firstStepNumber": first_step,
                    "lastStepNumber": last_step,
                })
            )
        # Per-amud mainTopic + overview: derive from the sugyot that touch
        # this amud, not the full window. So 2a's overview is about 2a, not
        # the whole 5-amud window's collective topic.
        if renumbered_sugyot:
            if len(renumbered_sugyot) == 1:
                amud_topic = renumbered_sugyot[0].topic
                amud_overview = renumbered_sugyot[0].gist
            else:
                topics = [sg.topic for sg in renumbered_sugyot]
                amud_topic = " · ".join(topics[:3])
                amud_overview = " ".join(
                    f"({i+1}) {sg.gist}" for i, sg in enumerate(renumbered_sugyot)
                )
        else:
            amud_topic = main_topic
            amud_overview = overview
        analysis = DafAnalysis(
            ref=f"{amud_data.source.masechet.replace('_', ' ')} {amud_data.daf}{amud_data.amud}",
            masechet=amud_data.masechet,
            daf=amud_data.daf,
            amud=amud_data.amud,  # type: ignore[arg-type]
            mainTopic=amud_topic,
            overview=amud_overview,
            sugyaBoundaries=renumbered_sugyot,
            steps=renumbered,
            pipelineVersion=PIPELINE_VERSION,
            generatedAt=_now_iso(),
            modelsUsed=models_used,
            cost=CostBreakdown(
                totalUSD=0.0,
                totalInputTokens=0,
                totalOutputTokens=0,
                byPass=seconds_by_pass,
            ),
        )
        out_pairs.append((label, analysis))

    return out_pairs


def build_window(
    masechet: str,
    amud_pairs: list[tuple[int, str]],
) -> list[Path]:
    """Process a window of consecutive amudim and write per-amud JSONs."""
    start = time.monotonic()
    out_dir = DEFAULT_OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    label = (
        f"{amud_pairs[0][0]}{amud_pairs[0][1]}-{amud_pairs[-1][0]}{amud_pairs[-1][1]}"
    )
    _log(start, f"=== Window: {masechet} {label} ===")
    _log(start, "Pass 0: fetching window from Sefaria…")
    window = asyncio.run(_fetch_window(masechet, amud_pairs))
    if not window:
        _log(start, "  → window empty (all amudim missing); skipping.")
        return []
    combined, amud_ranges = _concat_window(window)
    total_meforshim = sum(
        len(v) for a in window for v in a.by_anchor.values()
    )
    _log(
        start,
        f"  → {len(window)} amudim, {len(combined.hebrew)} Hebrew lines, {total_meforshim} meforshim.",
    )

    by_anchor: dict[str, list[MeforeshWithText]] = {}
    for a in window:
        for k, v in a.by_anchor.items():
            by_anchor.setdefault(k, []).extend(v)

    # FAST-PATH RESUME: if a 'polished' checkpoint exists, the LM work is done.
    # Skip directly to writing per-amud JSONs. Other partial resumes (structured,
    # phrased, meforshim) would need a bigger refactor; for now they just inform
    # debugging — the rebuild starts from scratch.
    checkpoint = _load_checkpoint(label)
    if checkpoint and checkpoint.get("stage") == "polished":
        from schema import SugyaBoundary as _SB
        _log(start, "  ↩ found 'polished' checkpoint, fast-forwarding to output split.")
        seg = SegmentResult(
            mainTopic=checkpoint["main_topic"],
            overview=checkpoint["overview"],
            sugyot=[_SB.model_validate(sg) for sg in checkpoint["sugyot"]],
        )
        all_steps = [Step.model_validate(s) for s in checkpoint["steps"]]
        step_line_ranges = [tuple(r) for r in checkpoint["step_line_ranges"]]
        _log(start, "Splitting window output per amud…")
        out_pairs = _split_to_amud_jsons(
            window=window, combined=combined, amud_ranges=amud_ranges,
            sugyot=seg.sugyot, steps=all_steps, step_line_ranges=step_line_ranges,
            models_used={}, seconds_by_pass={},
            main_topic=seg.mainTopic, overview=seg.overview,
        )
        written: list[Path] = []
        for label_str, analysis in out_pairs:
            out_file = out_dir / f"{masechet}_{label_str}.json"
            out_file.write_text(
                json.dumps(analysis.model_dump(exclude_none=True), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            _log(start, f"  → wrote {out_file.name}")
            written.append(out_file)
        _clear_checkpoint(label)
        _log(start, f"=== window resumed and complete in {int(time.monotonic() - start)}s ===")
        return written

    with LMStudioClient() as client:
        _log(start, f"Pass 1: segmenting {len(combined.hebrew)} lines across {len(window)} amudim…")
        seg: SegmentResult = segment_amud(client, combined)  # type: ignore[arg-type]
        _log(start, f"  → {len(seg.sugyot)} sugyot identified.")

        _log(start, "Pass 2: building structural skeleton for each sugya…")
        next_step_number = 1
        MAX_LINES_PER_STRUCTURE_CALL = 25
        # Some sugyot come back huge (under-segmented). Splitting them into
        # smaller chunks for the structure pass prevents Qwen from generating
        # a runaway response that triggers connection drops.
        expanded_sugyot: list[SugyaBoundary] = []
        for sg in seg.sugyot:
            span = sg.endLine - sg.startLine + 1
            if span <= MAX_LINES_PER_STRUCTURE_CALL:
                expanded_sugyot.append(sg)
                continue
            # Slice into chunks of MAX_LINES_PER_STRUCTURE_CALL each.
            chunks = (span + MAX_LINES_PER_STRUCTURE_CALL - 1) // MAX_LINES_PER_STRUCTURE_CALL
            chunk_size = (span + chunks - 1) // chunks
            for i in range(chunks):
                start_line = sg.startLine + i * chunk_size
                end_line = min(sg.endLine, start_line + chunk_size - 1)
                expanded_sugyot.append(sg.model_copy(update={
                    "startLine": start_line,
                    "endLine": end_line,
                    "topic": f"{sg.topic} (part {i+1}/{chunks})" if chunks > 1 else sg.topic,
                }))
            _log(start, f"  ⚠ sugya '{sg.topic[:50]}' was {span} lines — split into {chunks} chunks for structure pass.")
        for sugya in expanded_sugyot:
            _log(start, f"  · sugya {sugya.sugyaNumber} ({sugya.topic[:50]})")
            skeletons = structure_sugya(client, combined, sugya, next_step_number)  # type: ignore[arg-type]
            offset = sugya.startLine - 1
            for sk in skeletons:
                start_in = offset + max(1, sk.startLineInSugya)
                end_in = offset + max(sk.startLineInSugya, sk.endLineInSugya)
                end_in = min(end_in, sugya.endLine)
                start_in = min(start_in, end_in)
                step_line_ranges.append((start_in, end_in))
                all_steps.append(skeleton_to_step(sk))
            if skeletons:
                next_step_number = skeletons[-1].stepNumber + 1

        # Dedupe consecutive duplicate-range steps.
        ded_steps: list[Step] = []
        ded_ranges: list[tuple[int, int]] = []
        dropped = 0
        for s, rng in zip(all_steps, step_line_ranges, strict=True):
            if ded_ranges and rng == ded_ranges[-1]:
                dropped += 1
                continue
            ded_steps.append(s)
            ded_ranges.append(rng)
        if dropped:
            _log(start, f"  → dropped {dropped} duplicate consecutive step(s).")
            ded_steps = [s.model_copy(update={"stepNumber": i + 1}) for i, s in enumerate(ded_steps)]
        all_steps, step_line_ranges = ded_steps, ded_ranges
        _log(start, f"  → {len(all_steps)} total steps across window.")

        # Pass 2.5a (deterministic): source-grounded classification override.
        # If the Aramaic matches a hard pattern (e.g. "תא שמע", "ואידך", "וצריכא")
        # but the model labeled it wrong, force the right label.
        step_dicts = [s.model_dump() for s in all_steps]
        _, overrides = apply_source_checks(step_dicts)
        if overrides:
            _log(start, f"  → source-check forced {len(overrides)} classification overrides.")

        # Pass 2.5b (LM): independent verifier re-classifies each step with
        # neighbor context. Only high-confidence disagreements get applied.
        from verify_classifications import verify_steps_in_memory
        _log(start, "Pass 2.5: LM verifier auditing classifications…")
        n_changed, change_log = verify_steps_in_memory(
            client, combined.ref, step_dicts
        )
        if n_changed:
            _log(start, f"  → verifier corrected {n_changed} classification(s).")

        from schema import Step as _Step
        all_steps = [_Step.model_validate(sd) for sd in step_dicts]

        # CHECKPOINT after structure + verifier. If anything downstream fails
        # we resume here.
        _save_checkpoint(label, "structured", {
            "main_topic": seg.mainTopic,
            "overview": seg.overview,
            "sugyot": [sg.model_dump() for sg in seg.sugyot],
            "steps": [s.model_dump() for s in all_steps],
            "step_line_ranges": step_line_ranges,
        })

        _log(start, "Pass 3a: phrase split (deterministic)…")
        all_steps = _attach_phrases(combined, all_steps, step_line_ranges)
        _log(start, "Pass 3b: phrase alignment to Sefaria English…")
        step_english_chunks = [
            _aramaic_chunk(combined, s, e)[1] for s, e in step_line_ranges
        ]
        all_steps = translate_all_steps(client, all_steps, step_english_chunks)
        _log(start, "  → phrases attached and English aligned.")
        _save_checkpoint(label, "phrased", {
            "main_topic": seg.mainTopic,
            "overview": seg.overview,
            "sugyot": [sg.model_dump() for sg in seg.sugyot],
            "steps": [s.model_dump() for s in all_steps],
            "step_line_ranges": step_line_ranges,
        })

        if by_anchor:
            _log(start, "Pass 4: meforshim grounding…")
            # The combined `daf.ref` doesn't match anchor refs (which use per-amud
            # refs). Override: pass each step's line range against the right anchor
            # ref. We need to convert window line → per-amud ref+line.
            # For simplicity: build a per-anchor lookup AS-IS (anchor refs are
            # already keyed to per-amud refs like "Bava Metzia 3a:5"), and adjust
            # the per-step daf.ref to match the amud that step belongs to.
            enriched: list[Step] = []
            for step, rng in zip(all_steps, step_line_ranges, strict=True):
                owner = _which_amud(rng[0], amud_ranges)
                if not owner:
                    enriched.append(step)
                    continue
                owner_data = next(a for a in window if f"{a.daf}{a.amud}" == owner)
                local_start = rng[0] - next(s for s, _, lbl in amud_ranges if lbl == owner) + 1
                local_end = rng[1] - next(s for s, _, lbl in amud_ranges if lbl == owner) + 1
                local_end = min(local_end, len(owner_data.source.hebrew))
                local_start = max(1, local_start)
                # Single-step enrichment via existing infrastructure.
                step_e = enrich_steps(
                    client,
                    owner_data.source,
                    [step],
                    [(local_start, local_end)],
                    owner_data.by_anchor,
                )
                enriched.append(step_e[0])
            all_steps = enriched
            cnt = sum(1 for s in all_steps if s.meforshim and (
                s.meforshim.rashi or s.meforshim.tosafot or s.meforshim.rishonim or s.meforshim.acharonim
            ))
            _log(start, f"  → {cnt}/{len(all_steps)} steps enriched.")
        _save_checkpoint(label, "meforshim", {
            "main_topic": seg.mainTopic,
            "overview": seg.overview,
            "sugyot": [sg.model_dump() for sg in seg.sugyot],
            "steps": [s.model_dump() for s in all_steps],
            "step_line_ranges": step_line_ranges,
        })

        _log(start, "Pass 5: teaching-layer polish…")
        all_steps = polish_steps(client, all_steps)
        _log(start, "  → polished.")
        _save_checkpoint(label, "polished", {
            "main_topic": seg.mainTopic,
            "overview": seg.overview,
            "sugyot": [sg.model_dump() for sg in seg.sugyot],
            "steps": [s.model_dump() for s in all_steps],
            "step_line_ranges": step_line_ranges,
        })

    seconds_by_pass = client.by_pass_seconds()
    models_used = client.models_used()

    _log(start, "Splitting window output per amud…")
    out_pairs = _split_to_amud_jsons(
        window=window,
        combined=combined,
        amud_ranges=amud_ranges,
        sugyot=seg.sugyot,
        steps=all_steps,
        step_line_ranges=step_line_ranges,
        models_used=models_used,
        seconds_by_pass=seconds_by_pass,
        main_topic=seg.mainTopic,
        overview=seg.overview,
    )

    written: list[Path] = []
    for label_str, analysis in out_pairs:
        out_file = out_dir / f"{masechet}_{label_str}.json"
        out_file.write_text(
            json.dumps(analysis.model_dump(exclude_none=True), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _log(start, f"  → wrote {out_file.name} ({len(analysis.steps)} steps)")
        written.append(out_file)

    _clear_checkpoint(label)
    _log(start, f"=== window complete in {int(time.monotonic() - start) // 60}m{int(time.monotonic() - start) % 60:02d}s ===")
    return written


def main(argv: list[str] | None = None) -> int:
    import argparse, sys

    p = argparse.ArgumentParser()
    p.add_argument("masechet")
    p.add_argument("amudim", nargs="+", help="e.g. 2a 2b 3a 3b 4a")
    args = p.parse_args(argv or sys.argv[1:])
    pairs: list[tuple[int, str]] = []
    for s in args.amudim:
        s = s.strip().lower()
        if not s or s[-1] not in {"a", "b"} or not s[:-1].isdigit():
            print(f"bad daf {s}", file=__import__("sys").stderr)
            return 2
        pairs.append((int(s[:-1]), s[-1]))
    build_window(args.masechet, pairs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
