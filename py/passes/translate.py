"""Pass 3.5: align Sefaria's clean English to the Aramaic phrase split.

The deterministic phrasemap gives us perfect Aramaic phrases. Sefaria's Community
Translation gives us perfect fluent English at the SEGMENT level. The mismatch is
that segment boundaries don't align with phrase boundaries.

This module asks the LM to be an ALIGNER (not a translator): given the Aramaic
phrase list AND the Community Translation prose, slice the prose into the same
number of English phrases, parallel to the Aramaic. The LM should NOT invent
translations — it should redistribute the English text to match phrase
boundaries, only filling small gaps when needed.

This produces fluent native English (because we're slicing native prose) instead
of literal word-by-word Gemma output."""

from __future__ import annotations

from pydantic import BaseModel, Field

from llm import LMStudioClient
from schema import Phrase, Step

SYSTEM = """You are producing English for a list of Aramaic/Hebrew Talmudic phrases. Two outputs per phrase:

1. english[i]: a LITERAL English translation of aramaic[i]. Short. Word-by-word fidelity to the Aramaic.
2. notes[i]: an OPTIONAL brief explanation (one sentence max, or empty string) ONLY when the literal translation would confuse an English reader. Most phrases need NO notes — leave them empty.

INPUT:
- An ORDERED list of Aramaic phrases (never change this list).
- A block of reference English prose. CAVEAT: this is often Sefaria's William Davidson / Steinsaltz translation, which INTERLEAVES commentary into the translation. Treat commentary as NOISE for english[]; the commentary content may inform notes[] sparingly.

RULES FOR english[]:
- LITERAL. Word-for-word. If the Aramaic is "וכמה?" the english is "And how much?" — not "What is the criterion for amount of scattered produce?"
- BRIEF. Match the Aramaic length closely. Typically 4-15 English words for a 4-8 word Aramaic phrase. ABSOLUTELY NEVER more than 2× the Aramaic word count.
- NO commentary. NO explanations like "The Gemara asks", "This means", "because of the principle that…". Just the translation of the words.
- Connectors translate as connectors: "וְ" → "and", "אֲבָל" → "but", "אִי" → "if", "מָה" → "what".
- Keep proper nouns and technical terms in Hebrew script: טַלִּית, רַבִּי יִצְחָק, בבא קמא — not "tallit", "Rabbi Yitzchak", "Bava Kamma".

RULES FOR notes[]:
- USE SPARINGLY. Most phrases should have notes = "" (empty string).
- One sentence max, plain English. Just enough to bridge a confusion an English reader would have.
- DO NOT echo the literal translation in the notes. DO NOT include "The Gemara…" or "This means…" — start the note with the actual context if any.
- Examples of when notes ARE warranted:
  - Aramaic uses an idiom that's literal-untranslatable ("עלמא דאמת" — note: "the world of truth = the world to come")
  - The phrase points to a specific Mishnah/Gemara case not yet introduced
  - A technical halachic term whose meaning the reader needs

CORRECT EXAMPLE:
  aramaic[0] = "קב שומשמין בארבע אמות, מהו?"
  english[0] = "A kav of sesame seeds in four cubits — what is the law?"
  notes[0]   = ""   ← literal is clear, no notes needed

  aramaic[1] = "משום דנפיש טרחייהו"
  english[1] = "Because their labor is great"
  notes[1]   = ""

  aramaic[2] = "ההוא רעיא"
  english[2] = "That shepherd"
  notes[2]   = "Refers to the case introduced earlier — a shepherd who denied receiving sheep."   ← context worth adding

WRONG EXAMPLE:
  aramaic[0] = "קב שומשמין בארבע אמות, מהו?"
  english[0] = "If one kav of dates was scattered with a dispersal ratio of one kav in an area of four by four cubits, or if one kav of pomegranates was scattered with a dispersal ratio of one kav in an area of four by four cubits, what is the halakha?"
  ← FAR TOO LONG. This is Steinsaltz commentary embedded into translation. Strip it.

The output arrays MUST have exactly the same length as the input phrase list.

Return strict JSON: { english: [str, ...], notes: [str, ...] }."""


class AlignResponse(BaseModel):
    english: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def _user_prompt(phrases: list[str], english_prose: str) -> str:
    numbered = "\n".join(f"[{i+1}] {p}" for i, p in enumerate(phrases))
    return f"""Aramaic phrases (ordered, do NOT modify the list):
{numbered}

English prose (the translation source — slice this, do not invent):
{english_prose}

Return a JSON array `english` of length {len(phrases)}, parallel to the Aramaic list."""


def translate_step_phrases(
    client: LMStudioClient,
    step: Step,
    step_english: str,
) -> list[Phrase]:
    """Align Sefaria's English to the step's Aramaic phrase split."""
    if not step.phrases:
        return step.phrases
    aramaic = [p.aramaic for p in step.phrases]
    # If no reference English is available, the prompt still instructs the LM
    # to translate directly. Pass a sentinel so the LM knows it's translating
    # rather than aligning.
    if not step_english.strip():
        step_english = "(no reference English available — translate each Aramaic phrase literally into brief English)"
    try:
        result = client.call_json(
            pass_name="translate",  # routes to a bigger model (Qwen 27B) for accuracy
            system=SYSTEM,
            user=_user_prompt(aramaic, step_english),
            response_model=AlignResponse,
            max_tokens=8000,
        )
    except Exception as e:
        print(f"[translate] step {step.stepNumber} fell back to deterministic slice: {e}")
        return step.phrases
    english = list(result.english)
    notes = list(result.notes) if result.notes else []
    # Pad/trim to match aramaic length.
    if len(english) != len(aramaic):
        if len(english) < len(aramaic):
            english = english + [""] * (len(aramaic) - len(english))
        else:
            english = english[: len(aramaic)]
    if len(notes) != len(aramaic):
        if len(notes) < len(aramaic):
            notes = notes + [""] * (len(aramaic) - len(notes))
        else:
            notes = notes[: len(aramaic)]

    import re as _re
    out: list[Phrase] = []
    for i, p in enumerate(step.phrases):
        en = (english[i] or "").strip()
        note = (notes[i] or "").strip() if i < len(notes) else ""
        # Hard guardrail: English shouldn't exceed 2.5× the Aramaic word count.
        # If it does, the model leaked commentary — truncate aggressively.
        ar_words = len(_re.findall(r"\S+", p.aramaic))
        en_words = en.split()
        max_words = max(15, int(ar_words * 2.5))
        if len(en_words) > max_words:
            # Salvage: truncate to first sentence, or hard-cap by word count.
            sentences = _re.split(r"(?<=[\.!?])\s+", en, maxsplit=1)
            truncated = sentences[0] if sentences else en
            tw = truncated.split()
            if len(tw) > max_words:
                truncated = " ".join(tw[:max_words]) + "…"
            en = truncated
        # Note also has a length cap (~one sentence).
        if len(note.split()) > 40:
            note = " ".join(note.split()[:40]) + "…"
        out.append(
            Phrase(
                phraseNumber=p.phraseNumber,
                aramaic=p.aramaic,
                english=en if en else (p.english or ""),
                notes=note if note else None,
            )
        )
    return out


def translate_all_steps(
    client: LMStudioClient,
    steps: list[Step],
    step_english_chunks: list[str],
) -> list[Step]:
    """step_english_chunks is the parallel list of English text per step, sliced
    by the build orchestrator from the daf's full Community Translation."""
    out: list[Step] = []
    for i, s in enumerate(steps):
        en = step_english_chunks[i] if i < len(step_english_chunks) else ""
        out.append(s.model_copy(update={"phrases": translate_step_phrases(client, s, en)}))
    return out


__all__ = ["translate_all_steps"]
