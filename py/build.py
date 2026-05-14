"""Build a Gemara Clarity daf analysis using the local-first Python pipeline.

Usage:
    py build.py Bava_Metzia 2a
    py build.py Berakhot 5b --no-meforshim
    py build.py Bava_Metzia 2a --out custom/path.json

Writes:
    v2/public/data/<Masechet>_<Daf><Amud>.json         — main analysis (frontend-ready)
    v2/public/data/<Masechet>_<Daf><Amud>.review.json  — validation report (sidecar)

No cloud LLM calls. Sefaria is the only network egress. The pipeline talks to
LM Studio on the LAN — override the endpoint with LMSTUDIO_BASE_URL."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from llm import LMStudioClient
from passes.meforshim import enrich_steps
from passes.phrasemap import build_phrases_for_step
from passes.segment import segment_amud
from passes.structure import skeleton_to_step, structure_sugya
from passes.teaching import polish_steps
from passes.translate import translate_all_steps
from passes.validate import review_analysis
from schema import CostBreakdown, DafAnalysis, Step, SugyaBoundary
from sefaria import (
    DafSource,
    fetch_daf_text,
    fetch_meforshim_by_anchor,
)

PIPELINE_VERSION = "py-local-1"
DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "public" / "data"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _fmt_elapsed(start: float) -> str:
    s = int(time.monotonic() - start)
    return f"[{s // 60:d}m{s % 60:02d}s]"


def _log(start: float, msg: str) -> None:
    print(f"{_fmt_elapsed(start)} {msg}", flush=True)


async def _fetch_daf_async(masechet: str, daf: int, amud: str) -> DafSource:
    async with httpx.AsyncClient(timeout=60) as c:
        return await fetch_daf_text(c, masechet, daf, amud)


def _aramaic_chunk(daf: DafSource, start_line: int, end_line: int) -> tuple[str, str]:
    """Slice the Hebrew by line range, and the English by PROPORTION of the full
    daf — because the Sefaria Community Translation often has fewer (consolidated)
    segments than the Hebrew, so a 1:1 index mapping is wrong."""
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
    en = " ".join(en_words[en_start:en_end])
    return he, en


def _attach_phrases(
    daf: DafSource,
    steps: list[Step],
    step_line_ranges: list[tuple[int, int]],
) -> list[Step]:
    out: list[Step] = []
    for step, (start, end) in zip(steps, step_line_ranges, strict=True):
        ar, en = _aramaic_chunk(daf, start, end)
        if not ar.strip():
            out.append(step)
            continue
        out.append(step.model_copy(update={"phrases": build_phrases_for_step(ar, en)}))
    return out


def build(
    masechet: str,
    daf_num: int,
    amud: str,
    *,
    use_meforshim: bool = True,
    skip_teaching: bool = False,
    skip_validate: bool = False,
    out_path: Path | None = None,
) -> Path:
    start = time.monotonic()
    out_dir = (out_path.parent if out_path else DEFAULT_OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_path or out_dir / f"{masechet}_{daf_num}{amud}.json"
    review_file = out_file.with_suffix("") .with_suffix(".review.json")

    _log(start, f"Target: {masechet} {daf_num}{amud}")
    _log(start, f"Output: {out_file}")
    _log(start, f"Meforshim: {'ON' if use_meforshim else 'OFF'}")

    # Pass 0 (deterministic): pull source + commentaries from Sefaria.
    _log(start, f"Pass 0/6: fetching {masechet} {daf_num}{amud} from Sefaria…")
    daf = asyncio.run(_fetch_daf_async(masechet, daf_num, amud))
    _log(start, f"  → {len(daf.hebrew)} Hebrew lines, {len(daf.english)} English lines.")

    by_anchor: dict = {}
    if use_meforshim:
        _log(start, "Pass 0/6: fetching meforshim (Rashi + Tosafot) from Sefaria…")
        by_anchor = asyncio.run(fetch_meforshim_by_anchor(masechet, daf_num, amud))
        total = sum(len(v) for v in by_anchor.values())
        _log(start, f"  → {total} meforshim across {len(by_anchor)} anchors.")

    with LMStudioClient() as client:
        # Pass 1 (LM): segmentation.
        _log(start, f"Pass 1/6: segmenting {len(daf.hebrew)} lines into sugyot…")
        seg = segment_amud(client, daf)
        _log(start, f"  → {len(seg.sugyot)} sugyot identified.")

        # Pass 2 (LM): structure each sugya.
        _log(start, "Pass 2/6: building structural skeleton for each sugya…")
        all_steps: list[Step] = []
        step_line_ranges: list[tuple[int, int]] = []
        next_step_number = 1
        for sugya in seg.sugyot:
            _log(start, f"  · sugya {sugya.sugyaNumber} ({sugya.topic})")
            skeletons = structure_sugya(client, daf, sugya, next_step_number)
            offset = sugya.startLine - 1
            for sk in skeletons:
                start_in_daf = offset + max(1, sk.startLineInSugya)
                end_in_daf = offset + max(sk.startLineInSugya, sk.endLineInSugya)
                end_in_daf = min(end_in_daf, sugya.endLine)
                start_in_daf = min(start_in_daf, end_in_daf)
                step_line_ranges.append((start_in_daf, end_in_daf))
                all_steps.append(skeleton_to_step(sk))
            if skeletons:
                next_step_number = skeletons[-1].stepNumber + 1

        # Dedupe consecutive steps with identical line ranges — these are a
        # known structure-pass failure mode (Qwen sometimes emits two
        # consecutive steps both covering the same single trailing word
        # like "וּצְרִיכָא:" with different classifications). Keep the first.
        deduped_steps: list[Step] = []
        deduped_ranges: list[tuple[int, int]] = []
        dropped = 0
        for s, rng in zip(all_steps, step_line_ranges, strict=True):
            if deduped_ranges and rng == deduped_ranges[-1]:
                dropped += 1
                continue
            deduped_steps.append(s)
            deduped_ranges.append(rng)
        if dropped:
            _log(start, f"  → dropped {dropped} duplicate consecutive step(s).")
            # Renumber so stepNumber is contiguous 1..N.
            deduped_steps = [
                s.model_copy(update={"stepNumber": i + 1})
                for i, s in enumerate(deduped_steps)
            ]
        all_steps = deduped_steps
        step_line_ranges = deduped_ranges
        _log(start, f"  → {len(all_steps)} total steps across daf.")

        # Pass 3a (deterministic): phrase-by-phrase Aramaic split.
        _log(start, "Pass 3a: phrase split (deterministic, no AI)…")
        all_steps = _attach_phrases(daf, all_steps, step_line_ranges)
        # Pass 3b (LM): align Sefaria's English prose to the phrase split.
        _log(start, "Pass 3b: phrase alignment to Sefaria English…")
        step_english_chunks = [
            _aramaic_chunk(daf, sr[0], sr[1])[1] for sr in step_line_ranges
        ]
        all_steps = translate_all_steps(client, all_steps, step_english_chunks)
        _log(start, "  → phrases attached and English aligned.")

        # Pass 4 (LM): meforshim takeaways.
        if use_meforshim and by_anchor:
            _log(start, "Pass 4/6: meforshim grounding (Rashi / Tosafot)…")
            all_steps = enrich_steps(client, daf, all_steps, step_line_ranges, by_anchor)
            with_meforshim = sum(1 for s in all_steps if s.meforshim)
            _log(start, f"  → {with_meforshim}/{len(all_steps)} steps enriched.")
        else:
            _log(start, "Pass 4/6: skipped (no meforshim).")

        # Pass 5 (LM): teaching-layer polish.
        if not skip_teaching:
            _log(start, "Pass 5/6: teaching-layer polish (length, nikud, dedupe terms)…")
            all_steps = polish_steps(client, all_steps)
            _log(start, "  → polished.")
        else:
            _log(start, "Pass 5/6: skipped (--no-teaching).")

        # Update sugya boundaries with first/last step numbers covered.
        sugyot_with_steps: list[SugyaBoundary] = []
        for sugya in seg.sugyot:
            steps_in_sugya = [
                (i, s)
                for i, s in enumerate(all_steps)
                if sugya.startLine <= step_line_ranges[i][0] <= sugya.endLine
            ]
            first = steps_in_sugya[0][1].stepNumber if steps_in_sugya else None
            last = steps_in_sugya[-1][1].stepNumber if steps_in_sugya else None
            sugyot_with_steps.append(
                sugya.model_copy(update={"firstStepNumber": first, "lastStepNumber": last})
            )

        draft = DafAnalysis(
            ref=daf.ref,
            masechet=masechet,
            daf=daf_num,
            amud=amud,  # type: ignore[arg-type]
            mainTopic=seg.mainTopic,
            overview=seg.overview,
            sugyaBoundaries=sugyot_with_steps,
            steps=all_steps,
            pipelineVersion=PIPELINE_VERSION,
            generatedAt=_now_iso(),
            modelsUsed=client.models_used(),
            cost=CostBreakdown(
                totalUSD=0.0,
                totalInputTokens=sum(u.input_tokens for u in client.usage),
                totalOutputTokens=sum(u.output_tokens for u in client.usage),
                byPass=client.by_pass_seconds(),  # seconds, not USD — local is free
            ),
        )

        # Pass 6 (LM): validation re-read.
        review = None
        if not skip_validate:
            _log(start, "Pass 6/6: validation re-read (cross-model audit)…")
            try:
                review = review_analysis(client, daf, draft)
                n_crit = sum(1 for i in review.issues if i.severity == "critical")
                n_warn = sum(1 for i in review.issues if i.severity == "warning")
                n_nit = sum(1 for i in review.issues if i.severity == "nit")
                _log(
                    start,
                    f"  → overall: {review.overallAssessment} | "
                    f"{len(review.issues)} issues ({n_crit} critical, {n_warn} warning, {n_nit} nit)",
                )
            except Exception as e:
                _log(start, f"  ⚠ validation pass failed: {e}")
        else:
            _log(start, "Pass 6/6: skipped (--no-validate).")

    # Write outputs.
    out_file.write_text(
        json.dumps(draft.model_dump(exclude_none=True), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _log(start, f"Wrote {out_file}")
    if review is not None:
        review_file.write_text(
            json.dumps(review.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _log(start, f"Wrote {review_file}")

    total_tokens_in = sum(u.input_tokens for u in client.usage)
    total_tokens_out = sum(u.output_tokens for u in client.usage)
    _log(
        start,
        f"Done — {len(all_steps)} steps, {len(seg.sugyot)} sugyot, "
        f"{total_tokens_in:,} in / {total_tokens_out:,} out tokens. Cost: $0.00 (local).",
    )
    return out_file


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build a daf analysis locally.")
    p.add_argument("masechet", help="e.g. Bava_Metzia, Berakhot, Shabbat")
    p.add_argument("daf_amud", help="e.g. 2a, 5b, 22b")
    p.add_argument("--no-meforshim", action="store_true")
    p.add_argument("--no-teaching", action="store_true")
    p.add_argument("--no-validate", action="store_true")
    p.add_argument("--out", type=Path, default=None)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    ns = _parse_args(argv or sys.argv[1:])
    da = ns.daf_amud.strip().lower()
    if not da or da[-1] not in {"a", "b"} or not da[:-1].isdigit():
        print(f"daf_amud must look like '2a' or '5b' — got {ns.daf_amud}", file=sys.stderr)
        return 2
    build(
        masechet=ns.masechet,
        daf_num=int(da[:-1]),
        amud=da[-1],
        use_meforshim=not ns.no_meforshim,
        skip_teaching=ns.no_teaching,
        skip_validate=ns.no_validate,
        out_path=ns.out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
