"""Speed test: which model + thinking setting is fast AND produces correct output?
Streams progress for every model attempt so we know what's happening."""

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

# (model_id, enable_thinking_or_None)
TRIALS = [
    ("qwen/qwen3.6-27b", False),         # the optimization we want
    ("deepseek-r1-distill-llama-8b", False),  # small + fast
    ("deepseek-r1-distill-llama-8b", True),
    ("google/gemma-4-e4b", None),         # tiny model
    ("qwen/qwen3-coder-next", None),      # qwen non-thinking variant?
    ("nvidia/nemotron-3-super", None),
]


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


async def get_daf():
    async with httpx.AsyncClient(timeout=60) as c:
        return await fetch_daf_text(c, "Bava_Metzia", 2, "a")


def run(model: str, enable_thinking, schema, daf, sugya):
    label = f"{model} thinking={enable_thinking}"
    log(f">>> {label}")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": _user_prompt(daf, sugya, 1)},
        ],
        "max_tokens": 8000,  # tighter cap — bail early if too thinky
        "temperature": 0.1,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "StructureResponse",
                "strict": True,
                "schema": schema,
            },
        },
    }
    if enable_thinking is not None:
        payload["chat_template_kwargs"] = {"enable_thinking": enable_thinking}
    t0 = time.time()
    try:
        r = httpx.post(
            "http://10.6.15.101:1234/v1/chat/completions",
            json=payload,
            timeout=300,
        )
        r.raise_for_status()
    except httpx.HTTPError as e:
        log(f"  {label}: HTTP ERR after {time.time()-t0:.0f}s: {e}")
        return None
    out = r.json()
    msg = out["choices"][0]["message"]
    finish = out["choices"][0].get("finish_reason")
    usage = out.get("usage", {})
    elapsed = time.time() - t0
    content = (msg.get("content") or "").strip()
    reasoning = (msg.get("reasoning_content") or "").strip()
    body = content or reasoning
    reason_tok = usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
    completion_tok = usage.get("completion_tokens", 0)
    log(
        f"  {label}: {elapsed:.0f}s finish={finish} content={len(content)} "
        f"reasoning={len(reasoning)} reason_tok={reason_tok}/{completion_tok}"
    )
    if not body:
        log(f"  {label}: empty body")
        return (elapsed, 0)
    try:
        d = json.loads(body[body.find("{") : body.rfind("}") + 1])
        n = len(d.get("steps", []))
        log(f"  {label}: steps={n}")
        return (elapsed, n)
    except Exception as e:
        log(f"  {label}: parse fail: {e}")
        return (elapsed, 0)


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
    results = []
    for model, et in TRIALS:
        r = run(model, et, schema, daf, sugya)
        results.append((model, et, r))
    log("=== SUMMARY (speed, steps) ===")
    for model, et, r in results:
        log(f"  {model} thinking={et}: {r}")


if __name__ == "__main__":
    main()
