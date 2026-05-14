"""Pass 4: enrich each step with the verbatim Rashi / Tosafot Sefaria links to it,
and have a (smaller) local LM summarize each meforesh into a one-sentence takeaway.

Almost all of the value here is from Sefaria (the verbatim Hebrew text + the
anchor mapping). The LM only writes a single English sentence per commentary."""

from __future__ import annotations

from pydantic import BaseModel, Field

from llm import LMStudioClient
from schema import MeforeshComment, MeforshimBlock, Step
from sefaria import DafSource, MeforeshWithText

MAX_COMMENTARY_CHARS = 1800

RISHONIM = {
    "Ramban",
    "Rashba",
    "Ritva",
    "Ran",
    "Meiri",
    "Rabbeinu Yonah",
    "Rosh",
    "Mordechai",
}


def _bucket(title: str) -> str:
    if title == "Rashi":
        return "rashi"
    if title == "Tosafot":
        return "tosafot"
    return "rishonim" if title in RISHONIM else "acharonim"


def _truncate(s: str, max_chars: int = MAX_COMMENTARY_CHARS) -> str:
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + "…"


def _collect_for_step(
    by_anchor: dict[str, list[MeforeshWithText]],
    daf_ref: str,
    start_line: int,
    end_line: int,
) -> list[MeforeshWithText]:
    """Collect meforshim anchored to the lines this step actually covers.
    Previous version used len(step.phrases) which over-counted (the deterministic
    phrasemap produces 3-8-word phrases, not 1 per line) so every step pulled
    in meforshim from the whole daf."""
    out: list[MeforeshWithText] = []
    seen: set[str] = set()
    for line_num in range(start_line, end_line + 1):
        anchor = f"{daf_ref}:{line_num}"
        for m in by_anchor.get(anchor, []):
            if m.source_ref in seen:
                continue
            seen.add(m.source_ref)
            out.append(m)
    return out


SYSTEM = """You are an expert in classical commentaries (רש״י and תוספות) on the Talmud. Below you will receive:
1. A single Gemara step (with English explanation and Hebrew/Aramaic text).
2. The VERBATIM TEXTS of the linked commentaries Sefaria provides for that step's Gemara lines.

Your job is to:
- For each commentary entry that is materially relevant to this Gemara step, write a one-sentence English takeaway that captures what the meforesh is actually saying.

CRITICAL — NO TRANSLITERATION in the takeaway:
Write all Hebrew/Aramaic technical terms, sage names, masechtot, and concept names in HEBREW SCRIPT, never Latin letters.
CORRECT:  "רש״י explains that מציאה here means an unowned item, requiring no שבועה."
WRONG:    "Rashi explains that Metzi'ah here means an unowned item, requiring no Shevuah."
WRONG:    "...derived from a ברייתא in the תוספתא of ב'ava Metzia." (broken half-Hebrew names)
Required Hebrew script for: מציאה, קניין, שבועה, הלכה, חזקה, רב/רבי + names, רש״י, תוספות, מקח וממכר.
Masechet names: בבא מציעא (not Bava Metzia / ב'ava Metzia), בבא קמא, ברכות, שבת, קידושין, etc.
- INCLUDE EVERY relevant רש״י comment in the "rashi" array.
- INCLUDE EVERY relevant תוספות comment in the "tosafot" array.
- DO NOT invent or paraphrase content that isn't grounded in the verbatim Hebrew you were given.
- DO NOT include comments that are empty, irrelevant, or just glossing a single word with no analytical content.
- If multiple entries on the same step say substantively the same thing, consolidate.
- interplaySummary (optional, 1-2 sentences): ONLY when there's a meaningful disagreement or sequence between רש״י and תוספות on this step. If they all agree, omit / leave null.

Return strict JSON matching the schema."""


class _MTakeaway(BaseModel):
    sourceRef: str
    takeaway: str


class _MTakeawayWithTitle(BaseModel):
    sourceRef: str
    collectiveTitle: str | None = None
    takeaway: str


class MeforshimResponse(BaseModel):
    rashi: list[_MTakeaway] = Field(default_factory=list)
    tosafot: list[_MTakeaway] = Field(default_factory=list)
    rishonim: list[_MTakeawayWithTitle] = Field(default_factory=list)
    acharonim: list[_MTakeawayWithTitle] = Field(default_factory=list)
    interplaySummary: str | None = None


def _user_prompt(step: Step, meforshim: list[MeforeshWithText], daf: DafSource) -> str:
    step_text = " ".join(p.aramaic for p in step.phrases)
    bits: list[str] = []
    for m in meforshim:
        en_block = _truncate(m.english) if m.english else "[no English available]"
        bits.append(
            f"<<{m.collective_title} | {m.source_ref}>>\n"
            f"HEBREW: {_truncate(m.hebrew)}\n"
            f"ENGLISH: {en_block}"
        )
    meforshim_block = "\n\n".join(bits) or "[No meforshim were linked to this step on Sefaria.]"
    return f"""Gemara reference: {daf.ref}
Step #{step.stepNumber} ({step.hebrewStepName}) — {step.title}

Gemara text for this step:
{step_text}

Plain-English summary of the step (for context):
{step.whatsHappening}
{step.deeperAnalysis}

Verbatim meforshim linked to this step's Gemara lines:
{meforshim_block}

Now write structured takeaways from each materially relevant meforesh. Skip irrelevant or trivially-glossing comments."""


def enrich_steps(
    client: LMStudioClient,
    daf: DafSource,
    steps: list[Step],
    step_line_ranges: list[tuple[int, int]],
    by_anchor: dict[str, list[MeforeshWithText]],
) -> list[Step]:
    """step_line_ranges is a parallel list of (start_line, end_line) for each step
    in the daf. Used to scope each step's meforshim to its actual lines."""
    if not by_anchor:
        return steps
    out: list[Step] = []
    for i, step in enumerate(steps):
        rng = step_line_ranges[i] if i < len(step_line_ranges) else (1, 1)
        start_line, end_line = rng
        candidates = _collect_for_step(by_anchor, daf.ref, start_line, end_line)
        if not candidates:
            out.append(step)
            continue
        try:
            parsed = client.call_json(
                pass_name="meforshim",
                system=SYSTEM,
                user=_user_prompt(step, candidates, daf),
                response_model=MeforshimResponse,
                max_tokens=20000,
            )
        except Exception as e:
            print(f"[meforshim] step {step.stepNumber} failed: {e}")
            out.append(step)
            continue
        out.append(step.model_copy(update={"meforshim": _assemble(parsed, candidates)}))
    return out


def _assemble(
    parsed: MeforshimResponse, candidates: list[MeforeshWithText]
) -> MeforshimBlock:
    # The model often abbreviates the sourceRef ("Bava Metzia 2b:1:1" instead of
    # Sefaria's full "Rashi on Bava Metzia 2b:1:1"). Build a tolerant lookup that
    # tries exact, then suffix, then any candidate ending in the model's string.
    lookup: dict[str, MeforeshWithText] = {}
    for c in candidates:
        lookup[c.source_ref] = c
        # Stripped: drop a leading "Rashi on " / "Tosafot on " / etc.
        for prefix in (
            "Rashi on ",
            "Tosafot on ",
            "Ramban on ",
            "Rashba on ",
            "Ritva on ",
            "Ran on ",
            "Meiri on ",
            "Rosh on ",
        ):
            if c.source_ref.startswith(prefix):
                lookup.setdefault(c.source_ref[len(prefix) :], c)

    def find(source_ref: str) -> MeforeshWithText | None:
        if source_ref in lookup:
            return lookup[source_ref]
        # Last-resort: any candidate whose ref ends with the model's string,
        # or vice-versa. Handles other prefix-strip cases the table missed.
        for c in candidates:
            if c.source_ref.endswith(source_ref) or source_ref.endswith(c.source_ref):
                return c
        return None

    def to_comment(t: _MTakeaway, default_source: str) -> MeforeshComment:
        c = find(t.sourceRef)
        return MeforeshComment(
            source=c.collective_title if c else default_source,
            ref=c.source_ref if c else t.sourceRef,
            hebrew=c.hebrew if c else "",
            english=c.english if c else None,
            takeaway=t.takeaway,
        )

    def to_comment_with_title(t: _MTakeawayWithTitle, default_source: str) -> MeforeshComment:
        c = find(t.sourceRef)
        return MeforeshComment(
            source=(c.collective_title if c else None) or t.collectiveTitle or default_source,
            ref=c.source_ref if c else t.sourceRef,
            hebrew=c.hebrew if c else "",
            english=c.english if c else None,
            takeaway=t.takeaway,
        )

    def keep(c: MeforeshComment) -> bool:
        # Drop entries where the model returned a ref that didn't match any
        # candidate (empty hebrew = lookup failed, takeaway has no verbatim
        # text behind it = looks fabricated to the reader).
        return bool(c.hebrew and c.hebrew.strip())

    def dedupe(items: list[MeforeshComment]) -> list[MeforeshComment]:
        seen: set[str] = set()
        out: list[MeforeshComment] = []
        for c in items:
            if c.ref in seen:
                continue
            seen.add(c.ref)
            out.append(c)
        return out

    return MeforshimBlock(
        rashi=dedupe([c for c in (to_comment(t, "Rashi") for t in parsed.rashi) if keep(c)]),
        tosafot=dedupe([c for c in (to_comment(t, "Tosafot") for t in parsed.tosafot) if keep(c)]),
        rishonim=dedupe([c for c in (to_comment_with_title(t, "Commentary") for t in parsed.rishonim) if keep(c)]),
        acharonim=dedupe([c for c in (to_comment_with_title(t, "Commentary") for t in parsed.acharonim) if keep(c)]),
        interplaySummary=parsed.interplaySummary,
    )


__all__ = ["enrich_steps"]
