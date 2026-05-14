"""Diagnose which local model produces complete structured output on the hardest
pass (structure pass with 12 lines and complex Talmud schema).
Run with `py -u _bakeoff.py` for unbuffered streaming output."""

from __future__ import annotations

import asyncio
import json
import sys
import time

import httpx

from llm import _pydantic_to_strict_schema
from passes.structure import SYSTEM, StructureResponse, _user_prompt
from schema import SugyaBoundary
from sefaria import fetch_daf_text

CANDIDATES = [
    "nvidia/nemotron-3-super",
    "qwen/qwen3.6-27b",
    "nousresearch/hermes-4-70b",
    "openai/gpt-oss-120b",
]


async def get_daf():
    async with httpx.AsyncClient(timeout=60) as c:
        return await fetch_daf_text(c, "Bava_Metzia", 2, "a")


def run_one(model: str, daf, schema: dict, fake_sugya: SugyaBoundary):
    print(f"--- {model} ---", flush=True)
    t0 = time.time()
    try:
        r = httpx.post(
            "http://10.6.15.101:1234/v1/chat/completions",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": _user_prompt(daf, fake_sugya, 1)},
                ],
                "max_tokens": 16000,
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
            timeout=900,
        )
    except Exception as e:
        print(f"  HTTP ERROR: {e}", flush=True)
        return None
    elapsed = time.time() - t0
    out = r.json()
    msg = out["choices"][0]["message"]
    finish = out["choices"][0].get("finish_reason")
    usage = out.get("usage", {})
    content = (msg.get("content") or "").strip()
    reasoning = (msg.get("reasoning_content") or "").strip()
    body = content or reasoning
    out_tok = usage.get("completion_tokens", 0)
    reason_tok = usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
    print(
        f"  elapsed={elapsed:.0f}s, finish={finish}, "
        f"completion={out_tok}, reasoning={reason_tok}, "
        f"content_len={len(content)}, reasoning_len={len(reasoning)}",
        flush=True,
    )
    if not body:
        print("  BODY EMPTY", flush=True)
        return None
    try:
        d = json.loads(body[body.find("{") : body.rfind("}") + 1])
        n_steps = len(d.get("steps", []))
        print(f"  steps={n_steps}", flush=True)
        for s in d.get("steps", [])[:3]:
            print(
                f"    [{s.get('stepNumber')}] {s.get('hebrewStepName')} — {(s.get('title') or '')[:60]}",
                flush=True,
            )
        return n_steps
    except Exception as e:
        print(f"  PARSE ERROR: {e}", flush=True)
        print(f"  body head: {body[:300]!r}", flush=True)
        return None


def main():
    daf = asyncio.run(get_daf())
    schema = _pydantic_to_strict_schema(StructureResponse)
    fake_sugya = SugyaBoundary(
        sugyaNumber=1,
        startLine=1,
        endLine=12,
        topic="Tallit dispute and laws of finds",
        gist="Two people holding a tallit, division and oaths",
        openingFormula="שנים אוחזין",
    )
    print(f"daf: {daf.ref}, {len(daf.hebrew)} lines", flush=True)
    sys.stdout.flush()
    results = {}
    for m in CANDIDATES:
        results[m] = run_one(m, daf, schema, fake_sugya)
    print()
    print("=== SUMMARY ===", flush=True)
    for m, n in results.items():
        print(f"  {m}: steps={n}", flush=True)


if __name__ == "__main__":
    main()
