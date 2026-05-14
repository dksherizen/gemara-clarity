"""Active-learning feedback server.

Listens on localhost:5174 for POSTs from the PWA when the user corrects a
step's classification, title, or other field. Two effects per submission:

1. The correction is IMMEDIATELY applied to the daf JSON on disk — so the PWA
   reflects the fix on its next reload.
2. The correction is appended to a JSONL training dataset
   (v2/public/data/_feedback.jsonl) for eventual LoRA fine-tuning.

Stdlib-only (http.server). No deps beyond Python 3.

Usage:
    py feedback_server.py
    # Then in PWA, hit "Suggest correction" — Vite proxies /api/feedback
    # to localhost:5174 (config in v2/vite.config.ts)."""

from __future__ import annotations

import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Lock

DATA_DIR = Path(__file__).resolve().parent.parent / "public" / "data"
FEEDBACK_FILE = DATA_DIR / "_feedback.jsonl"
PORT = 5175

_write_lock = Lock()


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _apply_correction(ref: str, step_number: int, field: str, new_value: str) -> tuple[bool, str]:
    """Apply correction in-place to the daf JSON. Returns (success, message)."""
    # ref like "Bava Metzia 5a" → file "Bava_Metzia_5a.json"
    parts = ref.strip().split()
    if len(parts) < 2:
        return False, f"bad ref: {ref!r}"
    daf_amud = parts[-1]
    masechet = "_".join(parts[:-1])
    json_path = DATA_DIR / f"{masechet}_{daf_amud}.json"
    if not json_path.exists():
        return False, f"file not found: {json_path}"
    try:
        d = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as e:
        return False, f"read failed: {e}"
    steps = d.get("steps") or []
    target = next((s for s in steps if s.get("stepNumber") == step_number), None)
    if target is None:
        return False, f"step {step_number} not found in {ref}"
    old_value = target.get(field)
    target[field] = new_value
    d["steps"] = steps
    try:
        json_path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        return False, f"write failed: {e}"
    return True, f"applied {field}: {old_value!r} → {new_value!r}"


def _append_training_example(record: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        with FEEDBACK_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


class FeedbackHandler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        # Lightweight health check + last 10 corrections.
        recent: list[dict] = []
        if FEEDBACK_FILE.exists():
            lines = FEEDBACK_FILE.read_text(encoding="utf-8").strip().splitlines()
            for line in lines[-10:]:
                try:
                    recent.append(json.loads(line))
                except Exception:
                    continue
        self._send(200, {"ok": True, "recent": recent, "count": _count_feedback()})

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in ("/api/feedback", "/feedback"):
            self._send(404, {"error": "unknown endpoint"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            self._send(400, {"error": f"bad JSON: {e}"})
            return

        # Required fields
        ref = body.get("ref")
        step_number = body.get("stepNumber")
        field = body.get("field")  # e.g., "hebrewStepName", "title"
        new_value = body.get("newValue")
        if not all([ref, step_number is not None, field, new_value is not None]):
            self._send(400, {"error": "missing required fields: ref, stepNumber, field, newValue"})
            return

        # Apply in-place to JSON
        success, msg = _apply_correction(ref, int(step_number), field, str(new_value))

        # Always log to training dataset (even if apply failed — gives context for debugging)
        record = {
            "ts": _now_iso(),
            "ref": ref,
            "stepNumber": step_number,
            "field": field,
            "oldValue": body.get("oldValue"),
            "newValue": new_value,
            "userNote": body.get("userNote") or "",
            "applied": success,
            "message": msg,
        }
        _append_training_example(record)

        self._send(200 if success else 422, {"ok": success, "message": msg})

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        # Quiet logging — only print errors.
        if args and isinstance(args[0], str) and (args[0].startswith("4") or args[0].startswith("5")):
            sys.stderr.write(f"[feedback {time.strftime('%H:%M:%S')}] {format % args}\n")


def _count_feedback() -> int:
    if not FEEDBACK_FILE.exists():
        return 0
    try:
        return sum(1 for _ in FEEDBACK_FILE.open(encoding="utf-8"))
    except Exception:
        return 0


def main() -> int:
    server = HTTPServer(("127.0.0.1", PORT), FeedbackHandler)
    print(f"feedback server listening on http://127.0.0.1:{PORT}", flush=True)
    print(f"  writes to: {FEEDBACK_FILE}", flush=True)
    print(f"  current corrections: {_count_feedback()}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping", flush=True)
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
