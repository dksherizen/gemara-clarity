"""Test gemma-4-e4b with bigger max_tokens — if it completes cleanly, we have
our producer."""

from __future__ import annotations

import asyncio
import json
import time

import httpx

from llm import _pydantic_to_strict_schema
from passes.structure import SYSTEM, StructureResponse, _user_prompt
from schema import SugyaBoundary
from sefaria import fetch_daf_text


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


async def get_daf():
    async with httpx.AsyncClient(timeout=60) as c:
        return await fetch_daf_text(c, "Bava_Metzia", 2, "a")


def run(max_tokens: int, schema, daf, sugya):
    log(f">>> gemma-4-e4b max_tokens={max_tokens}")
    t0 = time.time()
    r = httpx.post(
        "http://10.6.15.101:1234/v1/chat/completions",
        json={
            "model": "google/gemma-4-e4b",
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": _user_prompt(daf, sugya, 1)},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.1,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "StructureResponse",
                    "strict": True,
                    "schema": schema,
                },
            },
        },
        timeout=600,
    )
    elapsed = time.time() - t0
    out = r.json()
    msg = out["choices"][0]["message"]
    finish = out["choices"][0].get("finish_reason")
    content = (msg.get("content") or "").strip()
    log(f"  elapsed={elapsed:.0f}s finish={finish} content={len(content)}")
    if not content:
        log("  EMPTY")
        return None
    try:
        d = json.loads(content)
        n = len(d.get("steps", []))
        log(f"  steps={n}")
        for s in d.get("steps", [])[:3]:
            log(
                f"    [{s.get('stepNumber')}] {s.get('hebrewStepName')} — {(s.get('title') or '')[:60]}"
            )
        return n
    except Exception as e:
        log(f"  parse fail: {e}")
        log(f"  tail: {content[-200:]!r}")
        return None


def main():
    daf = asyncio.run(get_daf())
    schema = _pydantic_to_strict_schema(StructureResponse)
    sugya = SugyaBoundary(
        sugyaNumber=1,
        startLine=1,
        endLine=12,
        topic="Tallit dispute and laws of finds",
        gist="Two people holding a tallit, division and oaths",
        openingFormula="שנים אוחזין",
    )
    log(f"daf: {daf.ref}, {len(daf.hebrew)} lines")
    # Probe sweep: how much room does gemma actually need?
    for mt in (16000, 24000):
        if run(mt, schema, daf, sugya) is not None:
            log(f"WINNER: gemma-4-e4b @ max_tokens={mt}")
            break


if __name__ == "__main__":
    main()
