"""OpenAI-compatible client for LM Studio on the LAN.

The only AI in this pipeline runs through this module. Default endpoint targets the
user's LAN LM Studio at http://10.6.15.101:1234/v1; override via LMSTUDIO_BASE_URL.
The frontend's expensive json-coercion logic (LooseHebrewStepName, LooseSeverity, ...)
is unnecessary here because we use LM Studio's json_schema mode which guarantees
the response conforms to the Pydantic schema we pass in."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Literal, Type, TypeVar

import httpx
from pydantic import BaseModel

DEFAULT_BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://10.6.15.101:1234/v1")
DEFAULT_TIMEOUT_S = float(os.environ.get("LMSTUDIO_TIMEOUT", "1800"))  # 30 min — local 120B is slow

Pass = Literal["segmentation", "structure", "meforshim", "teaching", "translate", "validate"]

PASS_MODEL: dict[Pass, str] = {
    # ALL passes on Qwen 3.6 27B. Gemma was doing segmentation but under-segmented
    # long windows (returning 1 sugya for 80+ lines), which forced the structure
    # pass to chunk and slowed everything down. Qwen segments correctly.
    "segmentation": "qwen/qwen3.6-27b",
    "structure": "qwen/qwen3.6-27b",
    "teaching": "qwen/qwen3.6-27b",
    "meforshim": "qwen/qwen3.6-27b",
    "translate": "qwen/qwen3.6-27b",
    "validate": "qwen/qwen3.6-27b",
}

T = TypeVar("T", bound=BaseModel)


@dataclass
class CallUsage:
    pass_name: str
    model: str
    input_tokens: int
    output_tokens: int
    seconds: float


class LMStudioClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        pass_models: dict[Pass, str] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.pass_models = {**PASS_MODEL, **(pass_models or {})}
        self.usage: list[CallUsage] = []
        self._http = httpx.Client(timeout=timeout_s)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "LMStudioClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def call_json(
        self,
        *,
        pass_name: Pass,
        system: str,
        user: str,
        response_model: Type[T],
        max_tokens: int = 8000,
        temperature: float = 0.1,
        schema_name: str | None = None,
        enable_thinking: bool | None = None,
    ) -> T:
        """Make a chat completion, force structured output via json_schema, parse to
        the given Pydantic model. Raises httpx.HTTPError or pydantic.ValidationError.

        enable_thinking: when False, asks Qwen-family thinking models to skip the
        chain-of-thought stage and answer directly. 3-5x throughput when set."""
        model = self.pass_models[pass_name]
        schema = _pydantic_to_strict_schema(response_model)
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name or response_model.__name__,
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        if enable_thinking is not None:
            # LM Studio passes chat_template_kwargs through to the model's chat
            # template. Qwen 3 / DeepSeek-R1 distill honor enable_thinking.
            payload["chat_template_kwargs"] = {"enable_thinking": enable_thinking}

        # Retry with backoff on transient connection errors AND empty-content
        # responses (LM Studio sometimes returns 200 OK with empty content under
        # load or after a reload).
        max_attempts = 4
        last_err: Exception | None = None
        t0 = time.monotonic()
        data = None
        parsed: Any = None
        for attempt in range(1, max_attempts + 1):
            try:
                r = self._http.post(f"{self.base_url}/chat/completions", json=payload)
                r.raise_for_status()
                candidate = r.json()
                # Verify the response has parseable content before accepting.
                msg = candidate["choices"][0]["message"]
                content_preview = (
                    (msg.get("content") or "").strip()
                    or (msg.get("reasoning_content") or "").strip()
                )
                if not content_preview:
                    last_err = ValueError(f"{pass_name} empty-content response")
                    backoff = 2 ** attempt
                    print(
                        f"[llm] {pass_name} empty-content (attempt {attempt}/{max_attempts}); "
                        f"backing off {backoff}s",
                        flush=True,
                    )
                    time.sleep(backoff)
                    continue
                # Parse JSON inside the retry loop so a one-off prose-where-JSON-
                # belonged response gets re-rolled rather than killing the pass.
                candidate_parsed = _extract_json(content_preview)
                if candidate_parsed is None:
                    last_err = ValueError(
                        f"{pass_name}: model returned non-JSON despite json_schema mode:\n{content_preview[:800]}"
                    )
                    backoff = 2 ** attempt
                    print(
                        f"[llm] {pass_name} non-JSON output (attempt {attempt}/{max_attempts}); "
                        f"backing off {backoff}s",
                        flush=True,
                    )
                    time.sleep(backoff)
                    continue
                data = candidate
                parsed = candidate_parsed
                break
            except (httpx.ReadError, httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadTimeout) as e:
                last_err = e
                backoff = 2 ** attempt  # 2,4,8,16
                print(
                    f"[llm] {pass_name} transient {type(e).__name__} (attempt {attempt}/{max_attempts}); "
                    f"backing off {backoff}s",
                    flush=True,
                )
                time.sleep(backoff)
            except httpx.HTTPStatusError as e:
                # 5xx → always retry.
                # 400 "Model reloaded." → retry (LM Studio auto-reloads kill the call).
                # Other 4xx → fail fast (schema bug, won't be fixed by retrying).
                body_preview = ""
                try:
                    body_preview = e.response.text[:800]
                except Exception:
                    pass
                is_model_reload = e.response.status_code == 400 and "Model reloaded" in body_preview
                if 500 <= e.response.status_code < 600 or is_model_reload:
                    last_err = e
                    backoff = 2 ** attempt
                    reason = "model-reload" if is_model_reload else f"HTTP {e.response.status_code}"
                    print(
                        f"[llm] {pass_name} {reason} (attempt {attempt}/{max_attempts}); "
                        f"backing off {backoff}s",
                        flush=True,
                    )
                    time.sleep(backoff)
                else:
                    print(
                        f"[llm] {pass_name} HTTP {e.response.status_code} (permanent): {body_preview}",
                        flush=True,
                    )
                    raise
        else:
            assert last_err is not None
            raise last_err
        elapsed = time.monotonic() - t0
        usage = data.get("usage") or {}
        self.usage.append(
            CallUsage(
                pass_name=pass_name,
                model=model,
                input_tokens=int(usage.get("prompt_tokens", 0)),
                output_tokens=int(usage.get("completion_tokens", 0)),
                seconds=elapsed,
            )
        )
        return response_model.model_validate(parsed)

    def total_seconds(self) -> float:
        return sum(u.seconds for u in self.usage)

    def by_pass_seconds(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for u in self.usage:
            out[u.pass_name] = out.get(u.pass_name, 0.0) + u.seconds
        return out

    def models_used(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for u in self.usage:
            out[u.pass_name] = f"lmstudio/{u.model}"
        return out


# ---------- schema conversion ----------
#
# LM Studio's json_schema mode requires:
#   - "strict": true
#   - every property in "required"
#   - "additionalProperties": false
#   - no $ref / $defs (or all refs inlined)
#
# Pydantic by default emits $defs for nested models and marks Optional fields as
# not-required. We fix both by inlining $defs and forcing every property required
# (Optional fields get type ["string", "null"] etc. so the model can still emit null).


def _pydantic_to_strict_schema(model: Type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema()
    inlined = _inline_refs(raw)
    return _make_strict(inlined)


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    defs = schema.pop("$defs", {})
    if not defs:
        return schema

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref = node["$ref"]
                if ref.startswith("#/$defs/"):
                    name = ref[len("#/$defs/") :]
                    if name not in defs:
                        return node
                    return resolve(json.loads(json.dumps(defs[name])))
                return node
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(schema)


def _make_strict(node: Any) -> Any:
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"].keys())
            for k, v in node["properties"].items():
                node["properties"][k] = _make_strict(_widen_optional(v))
            return node
        if "anyOf" in node:
            node["anyOf"] = [_make_strict(opt) for opt in node["anyOf"]]
        if "items" in node:
            node["items"] = _make_strict(node["items"])
        return node
    if isinstance(node, list):
        return [_make_strict(item) for item in node]
    return node


def _widen_optional(node: dict[str, Any]) -> dict[str, Any]:
    """Pydantic emits Optional[X] as `anyOf: [X, {type: null}]`. LM Studio strict
    mode is happier with a clean schema that accepts null OR the value. We leave
    anyOf intact (json_schema 2020-12 supports it)."""
    return node


def _extract_json(text: str) -> Any:
    """Parse JSON from a model response. Tries direct json.loads first, then falls
    back to extracting the first top-level {...} or [...] from text that may have
    leading/trailing reasoning chatter (common in thinking models when json_schema
    output is routed to reasoning_content)."""
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Find the first JSON object/array by balanced-brace scan.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start < 0:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    return None


__all__ = ["LMStudioClient", "Pass", "PASS_MODEL", "CallUsage"]
