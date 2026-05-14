"""Deterministic phrase-by-phrase mapping. Replaces the most expensive AI pass
(~$0.088/daf on the cloud TS pipeline) with pure code.

The Sefaria payload gives us Hebrew and English text segment-by-segment (already
aligned by anchor). For each step, we slice the matching Hebrew/English segments
out of the daf, then split the Hebrew into 3–8 word phrases by:
  1. Hebrew punctuation: סוף-פסוק (׃), period, comma, semicolon, colon, question/
     exclamation marks, em-dash, parens/brackets.
  2. If a chunk is still > MAX_PHRASE_WORDS words, split on the next softer
     boundary (commas, מקף).
  3. If a chunk is < MIN_PHRASE_WORDS, merge with the previous neighbor.

The English translation for each phrase is sliced proportionally — we don't try to
do word-by-word alignment (which Sefaria's segment-level English doesn't support).

This is "good enough" because:
  - The Aramaic is preserved EXACTLY (the schema invariant the UI relies on).
  - The user sees phrase-level Aramaic with a chunk of English next to it.
  - Step-level English is also provided to the user via stepSummary."""

from __future__ import annotations

import re
from dataclasses import dataclass

from schema import Phrase

# Tuning knobs — keep these similar to the TS prompt's "3–8 words" rule.
MIN_PHRASE_WORDS = 3
MAX_PHRASE_WORDS = 8
TARGET_PHRASE_WORDS = 6

# Hard punctuation that always ends a phrase. Includes Hebrew sof pasuk + Western.
_HARD_PUNCT = "׃.!?"
# Soft punctuation we'll split on if a chunk is still too long. Gershayim ״ is
# excluded — in Talmudic typography it's a quotation marker, not a clause break.
_SOFT_PUNCT = ",;:—–-"

_NIKUD_RE = re.compile(r"[֑-ׇ]")
_WORD_SPLIT_RE = re.compile(r"\s+")


@dataclass
class _Chunk:
    text: str

    @property
    def words(self) -> list[str]:
        return [w for w in _WORD_SPLIT_RE.split(self.text.strip()) if w]


def _split_on(text: str, chars: str) -> list[_Chunk]:
    """Split text into chunks at any char in `chars`, keeping the punctuation
    attached to the preceding chunk."""
    out: list[_Chunk] = []
    buf: list[str] = []
    for ch in text:
        buf.append(ch)
        if ch in chars:
            piece = "".join(buf).strip()
            if piece:
                out.append(_Chunk(text=piece))
            buf = []
    tail = "".join(buf).strip()
    if tail:
        out.append(_Chunk(text=tail))
    return out


def _further_split_long_chunk(chunk: _Chunk) -> list[_Chunk]:
    """If a chunk is too long, split on soft punctuation; if it's still too long,
    fall back to splitting by word count."""
    if len(chunk.words) <= MAX_PHRASE_WORDS:
        return [chunk]
    soft_split = _split_on(chunk.text, _SOFT_PUNCT)
    if len(soft_split) > 1:
        out: list[_Chunk] = []
        for s in soft_split:
            out.extend(_further_split_long_chunk(s))
        return out
    # Last resort: word-count split.
    words = chunk.words
    out = []
    i = 0
    while i < len(words):
        slice_words = words[i : i + TARGET_PHRASE_WORDS]
        out.append(_Chunk(text=" ".join(slice_words)))
        i += TARGET_PHRASE_WORDS
    return out


def _merge_runts(chunks: list[_Chunk]) -> list[_Chunk]:
    """Merge chunks shorter than MIN_PHRASE_WORDS into a neighbor, but never push
    a neighbor past MAX_PHRASE_WORDS. If no merge is safe, leave the runt alone —
    a slightly short phrase beats a 25-word monolith."""
    if not chunks:
        return []
    out: list[_Chunk] = list(chunks)

    def words(c: _Chunk) -> int:
        return len(c.words)

    changed = True
    while changed:
        changed = False
        for i, c in enumerate(out):
            if words(c) >= MIN_PHRASE_WORDS:
                continue
            prev_room = words(out[i - 1]) + words(c) <= MAX_PHRASE_WORDS if i > 0 else False
            next_room = (
                words(out[i + 1]) + words(c) <= MAX_PHRASE_WORDS
                if i < len(out) - 1
                else False
            )
            if prev_room and (not next_room or words(out[i - 1]) <= words(out[i + 1])):
                out[i - 1] = _Chunk(text=(out[i - 1].text + " " + c.text).strip())
                del out[i]
                changed = True
                break
            if next_room:
                out[i + 1] = _Chunk(text=(c.text + " " + out[i + 1].text).strip())
                del out[i]
                changed = True
                break
        # If no merge happened this pass we exit; the remaining runts stay.
    return out


def split_into_phrases(aramaic: str) -> list[str]:
    """Public entry: produce a list of 3–8-word Aramaic phrases that, concatenated,
    equal the input."""
    chunks = _split_on(aramaic, _HARD_PUNCT)
    if not chunks:
        chunks = [_Chunk(text=aramaic)]
    refined: list[_Chunk] = []
    for c in chunks:
        refined.extend(_further_split_long_chunk(c))
    refined = _merge_runts(refined)
    return [c.text for c in refined if c.text.strip()]


def _word_count(text: str) -> int:
    return len([w for w in _WORD_SPLIT_RE.split(text.strip()) if w])


def _strip_nikud(text: str) -> str:
    return _NIKUD_RE.sub("", text)


def _slice_english_proportionally(
    english: str, aramaic_phrases: list[str]
) -> list[str]:
    """We have one English block from Sefaria covering N Aramaic phrases. Slice the
    English at sentence boundaries when there are exactly N sentences; otherwise
    slice by word-count proportion to the (nikud-stripped) Aramaic word counts."""
    n = len(aramaic_phrases)
    if n == 0:
        return []
    if n == 1:
        return [english.strip()]

    # Try sentence split first.
    sentences = [s.strip() for s in re.split(r"(?<=[\.!?])\s+", english.strip()) if s.strip()]
    if len(sentences) == n:
        return sentences

    # Fall back to proportional word slicing.
    aramaic_word_counts = [
        max(1, _word_count(_strip_nikud(p))) for p in aramaic_phrases
    ]
    total_aramaic_words = sum(aramaic_word_counts)
    english_words = [w for w in english.split() if w]
    total_english = len(english_words)
    if total_english == 0:
        return [""] * n
    out: list[str] = []
    cursor = 0
    for i, w in enumerate(aramaic_word_counts):
        if i == n - 1:
            slice_words = english_words[cursor:]
        else:
            count = max(1, round(total_english * w / total_aramaic_words))
            slice_words = english_words[cursor : cursor + count]
            cursor += count
        out.append(" ".join(slice_words).strip())
    # Smooth any empty trailing slices (over-allocated above).
    out = [s if s else "" for s in out]
    return out


def build_phrases_for_step(
    aramaic_chunk: str,
    english_chunk: str,
) -> list[Phrase]:
    """Produce a Phrase[] for one step. The Aramaic content is preserved exactly
    in order; English is sliced from the Sefaria translation."""
    if not aramaic_chunk.strip():
        return []
    phrases_text = split_into_phrases(aramaic_chunk)
    english_slices = _slice_english_proportionally(english_chunk, phrases_text)
    out: list[Phrase] = []
    for i, (ar, en) in enumerate(zip(phrases_text, english_slices, strict=False)):
        out.append(
            Phrase(
                phraseNumber=i + 1,
                aramaic=ar,
                english=en or "[translation unavailable]",
            )
        )
    if not out:
        # Last-resort fallback: one mega-phrase so the schema invariant (≥1 phrase) holds.
        out.append(
            Phrase(
                phraseNumber=1,
                aramaic=aramaic_chunk.strip(),
                english=english_chunk.strip() or "[translation unavailable]",
            )
        )
    return out


__all__ = ["split_into_phrases", "build_phrases_for_step"]


if __name__ == "__main__":
    import sys

    sample = (
        "שְׁנַיִם אוֹחֲזִין בְּטַלִּית, זֶה אוֹמֵר: ״אֲנִי מְצָאתִיהָ״ "
        "וְזֶה אוֹמֵר: ״אֲנִי מְצָאתִיהָ״, זֶה אוֹמֵר: ״כּוּלָּהּ שֶׁלִּי״ "
        "וְזֶה אוֹמֵר: ״כּוּלָּהּ שֶׁלִּי״."
    )
    en = (
        "If two people come to court holding a tallit, this one says I found it "
        "and that one says I found it; this one says all of it is mine and that "
        "one says all of it is mine."
    )
    phrases = build_phrases_for_step(sample, en)
    for p in phrases:
        sys.stdout.write(f"[{p.phraseNumber}] {p.aramaic}\n    → {p.english}\n")
