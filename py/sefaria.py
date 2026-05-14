"""Sefaria.org API fetchers. Zero AI here — everything is deterministic data pulls.

Mirrors v2/src/lib/sefaria/client.ts. The /api/texts endpoint gives us the Hebrew
source + Steinsaltz English translation for the daf. The /api/links endpoint gives
us every commentary attached to a daf, with anchorRef telling us which segment
each commentary attaches to."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

SEFARIA_BASE = "https://www.sefaria.org/api"

# Default meforshim. Sefaria's `collectiveTitle.en` is what we filter on.
CORE_MEFORSHIM: set[str] = {"Rashi", "Tosafot"}

# What we'd normally bucket as Rishonim, when the user opts in.
RISHONIM_TITLES: set[str] = {
    "Ramban",
    "Rashba",
    "Ritva",
    "Ran",
    "Meiri",
    "Rabbeinu Yonah",
    "Rosh",
    "Mordechai",
}


@dataclass
class DafSource:
    ref: str
    masechet: str
    daf: int
    amud: str  # "a" or "b"
    hebrew: list[str]
    english: list[str]


@dataclass
class MeforeshLink:
    collective_title: str
    hebrew_title: str
    anchor_ref: str
    source_ref: str
    category: str
    has_english: bool
    composition_year: int | None = None


@dataclass
class MeforeshWithText:
    link: MeforeshLink
    hebrew: str
    english: str

    @property
    def source_ref(self) -> str:
        return self.link.source_ref

    @property
    def anchor_ref(self) -> str:
        return self.link.anchor_ref

    @property
    def collective_title(self) -> str:
        return self.link.collective_title


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)


def _strip_html(s: str) -> str:
    s = _BR_RE.sub(" ", s)
    s = _TAG_RE.sub("", s)
    s = _WS_RE.sub(" ", s)
    return s.strip()


def _flatten(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out: list[str] = []
        for v in value:
            out.extend(_flatten(v))
        return out
    return []


async def _get_json(client: httpx.AsyncClient, url: str) -> Any:
    r = await client.get(url, headers={"Accept": "application/json"})
    r.raise_for_status()
    return r.json()


async def fetch_daf_text(
    client: httpx.AsyncClient,
    masechet: str,
    daf: int,
    amud: str,
) -> DafSource:
    """Fetch the daf's Hebrew/Aramaic + English translation.

    Strategy:
    - "Sefaria Community Translation" is clean literal text but doesn't cover
      every daf or every line (BM 2a only has 6 of 12 lines).
    - "William Davidson Edition" (the default) covers everything but interleaves
      Steinsaltz's commentary with the literal translation.

    We fetch both and merge: prefer Community segments when they exist for that
    line, fall back to William Davidson otherwise. The merged result is the
    same length as the Hebrew, ensuring downstream alignment can find SOMETHING
    to translate against for every phrase."""
    ref = f"{masechet}.{daf}{amud}"
    base_url = f"{SEFARIA_BASE}/texts/{ref}?context=0&commentary=0"
    data = await _get_json(client, base_url)
    hebrew = [_strip_html(s) for s in _flatten(data.get("he")) if s]
    hebrew = [s for s in hebrew if s]
    if not hebrew:
        raise RuntimeError(f"No Hebrew source returned for {ref}")

    default_en = [_strip_html(s) for s in _flatten(data.get("text")) if s]
    default_en = [s for s in default_en if s]

    # Try the literal translations first; fall back to William Davidson (default)
    # which has commentary baked in.
    community_en: list[str] = []
    sefaria_en: list[str] = []
    for label, params in [
        ("community", "&ven=Sefaria+Community+Translation"),
        ("sefaria", "&ven=Sefaria+translation"),
    ]:
        try:
            r = await _get_json(client, f"{base_url}{params}")
            texts = [_strip_html(s) for s in _flatten(r.get("text")) if s]
            texts = [s for s in texts if s and s.strip()]
            if label == "community":
                community_en = texts
            else:
                sefaria_en = texts
        except Exception:
            pass

    # Merge in priority order: community > sefaria_translation > default (William Davidson).
    english: list[str] = []
    for i in range(len(hebrew)):
        c = community_en[i] if i < len(community_en) else ""
        s = sefaria_en[i] if i < len(sefaria_en) else ""
        d = default_en[i] if i < len(default_en) else ""
        picked = c.strip() or s.strip() or d.strip()
        english.append(picked)
    if not any(english):
        english = community_en or sefaria_en or default_en

    return DafSource(
        ref=data.get("ref") or ref,
        masechet=masechet,
        daf=daf,
        amud=amud,
        hebrew=hebrew,
        english=english,
    )


async def fetch_links_for_daf(
    client: httpx.AsyncClient,
    masechet: str,
    daf: int,
    amud: str,
) -> list[dict[str, Any]]:
    ref = f"{masechet}.{daf}{amud}"
    url = f"{SEFARIA_BASE}/links/{ref}?with_text=0"
    return await _get_json(client, url)


def filter_meforshim(
    raw_links: list[dict[str, Any]],
    extra_seforim: set[str] | None = None,
    categories: set[str] | None = None,
) -> list[MeforeshLink]:
    allowed = CORE_MEFORSHIM | (extra_seforim or set())
    cats = categories or {"Commentary"}
    out: list[MeforeshLink] = []
    for row in raw_links:
        if row.get("category") not in cats:
            continue
        ct = row.get("collectiveTitle") or {}
        en = ct.get("en") or ""
        if en not in allowed:
            continue
        comp = row.get("compDate")
        comp_year = comp[0] if isinstance(comp, list) and comp else None
        out.append(
            MeforeshLink(
                collective_title=en,
                hebrew_title=ct.get("he") or "",
                anchor_ref=str(row.get("anchorRef") or ""),
                source_ref=str(row.get("sourceRef") or ""),
                category=str(row.get("category") or ""),
                has_english=bool(row.get("sourceHasEn")),
                composition_year=comp_year,
            )
        )
    return out


async def fetch_commentary_text(
    client: httpx.AsyncClient,
    source_ref: str,
) -> tuple[str, str]:
    url = f"{SEFARIA_BASE}/texts/{source_ref}?context=0&commentary=0"
    data = await _get_json(client, url)
    hebrew = " ".join(_strip_html(s) for s in _flatten(data.get("he")) if s).strip()
    english = " ".join(_strip_html(s) for s in _flatten(data.get("text")) if s).strip()
    return hebrew, english


async def fetch_meforshim_by_anchor(
    masechet: str,
    daf: int,
    amud: str,
    extra_seforim: set[str] | None = None,
    concurrency: int = 6,
) -> dict[str, list[MeforeshWithText]]:
    """Returns mapping of anchor_ref → list of meforshim attached to that segment."""
    async with httpx.AsyncClient(timeout=60) as client:
        raw_links = await fetch_links_for_daf(client, masechet, daf, amud)
        meforshim = filter_meforshim(raw_links, extra_seforim=extra_seforim)
        sem = asyncio.Semaphore(concurrency)

        async def fetch_one(link: MeforeshLink) -> MeforeshWithText:
            async with sem:
                try:
                    he, en = await fetch_commentary_text(client, link.source_ref)
                except Exception:
                    he, en = "", ""
                return MeforeshWithText(link=link, hebrew=he, english=en)

        results = await asyncio.gather(*(fetch_one(m) for m in meforshim))

    by_anchor: dict[str, list[MeforeshWithText]] = {}
    for m in results:
        by_anchor.setdefault(m.anchor_ref, []).append(m)
    return by_anchor


__all__ = [
    "DafSource",
    "MeforeshLink",
    "MeforeshWithText",
    "fetch_daf_text",
    "fetch_meforshim_by_anchor",
]


async def _selftest() -> None:
    async with httpx.AsyncClient(timeout=30) as c:
        d = await fetch_daf_text(c, "Bava_Metzia", 2, "a")
        print(f"{d.ref}: {len(d.hebrew)} Hebrew segments, {len(d.english)} English segments")
        print(f"  first Hebrew: {d.hebrew[0][:60]}...")
        print(f"  first English: {d.english[0][:60]}...")


if __name__ == "__main__":
    asyncio.run(_selftest())
