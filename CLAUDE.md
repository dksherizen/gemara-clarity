# Gemara Clarity — Local Pipeline

> 🔴 **READ `HANDOFF.md` FIRST** if you're picking this up from a cleared/new
> chat. That file has the live state (what's running, what's pending).
> This `CLAUDE.md` is the durable architecture reference.

PWA at `index.html` (Vite + React + TS) that renders Talmud daf analyses.
Backend is a Python pipeline in `py/` that calls a local LM Studio server.

## Quick start

```bash
# Run the dev server (the PWA)
npm run dev

# Build a single amud
cd py && py build.py Bava_Metzia 2a

# Build a whole tractate (detached, multi-day)
cd py
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUNBUFFERED="1"
Start-Process py "-u","batch_masechet.py","Bava_Metzia" `
  -RedirectStandardOutput "..\public\data\_batch_stdout.log" `
  -RedirectStandardError  "..\public\data\_batch_stderr.log" `
  -WindowStyle Hidden
```

## Architecture (the part that matters)

Each amud goes through **6 passes**, but the pipeline runs at the **window level
(5 consecutive amudim)** so sugyot can correctly span amud boundaries. Output is
written per-amud (the PWA reads per-amud JSONs).

```
Fetch (Sefaria, deterministic)
  → Pass 1: segmentation        — identify sugyot across the window
  → Pass 2: structure           — break each sugya into argumentative steps
  → Pass 3a: phrase split       — deterministic Aramaic chunking by punctuation
  → Pass 3b: phrase alignment   — LM aligns Sefaria English to phrases
  → Pass 4: meforshim grounding — LM writes Rashi/Tosafot takeaways
  → Pass 5: teaching polish     — LM tightens prose, dedupes key terms
  → Pass 6: validate (optional) — cross-model audit
Split → per-amud JSON files at public/data/{Masechet}_{daf}{amud}.json
```

### Model routing (`py/llm.py:PASS_MODEL`)

LM Studio at `http://10.6.15.101:1234/v1` (override with `LMSTUDIO_BASE_URL`).
- **Gemma-4-e4b**: segmentation only (small output, fast, non-thinking)
- **Qwen 3.6 27B** (thinking): structure, meforshim, teaching, translate, validate

Models with weak behavior in our bake-off (in `py/_bakeoff.py`):
- gpt-oss-120b: stubs out long responses, returns 1 step instead of 12
- Hermes 4 70B: HTTP timeouts on long structured-output calls
- DeepSeek R1 distill: rejects `response_format: json_schema` with 400

## Critical gotchas

### Sefaria translations are NOT phrase-aligned
The default English version (William Davidson / Steinsaltz) interleaves
**commentary** with translation. "Two men are holding onto a garment" gets
prefixed with "The early commentaries ask why this chapter..." — that's
narrative ABOUT the chapter, not translation.

Fix in `sefaria.py:fetch_daf_text`: prefer the **"Sefaria Community
Translation"** (a literal version), but fall back to William Davidson for
sections Community doesn't cover. Then merge per-line so Hebrew[i] always has a
corresponding English[i].

### Sugyot span amudim
Single-amud segmentation creates artificial sugya breaks at every amud
boundary. **Process 5-amud windows together**, then split output per amud,
marking cross-amud sugyot with "(continues)" prefix and a "continues into next
amud" suffix on the gist (`window_orchestrator._split_to_amud_jsons`).

### LM Studio strict json_schema
- All properties must be in `required` (OpenAI spec). Optional fields use
  `anyOf: [{type: T}, {type: null}]`.
- `additionalProperties: false` everywhere.
- Pydantic schemas go through `llm._pydantic_to_strict_schema()` which inlines
  `$refs` and adds the required/additionalProperties keys.

### LM Studio context length vs max_tokens
Two separate knobs:
- **Context length (n_ctx)** is set in LM Studio's model-load sidebar. Default
  is small (4-8k). For Gemma set to 131k; for Qwen 27B set to 128k.
- **max_tokens** in the API request controls output. Bumped per pass:
  segment 16k, structure 32k, meforshim 20k, teaching 16k, translate 8k.

If LM Studio is loaded with 8k context but you request 32k max_tokens, calls
will silently truncate or 400.

### Thinking models hide output in `reasoning_content`
Qwen 3 / DeepSeek R1 distill put structured-output JSON in
`reasoning_content`, leaving `content` empty. The client accepts whichever is
non-empty (`llm.py:call_json`). Without this, every Qwen call looks "broken."

### Connection drops on long calls (WinError 10054)
LAN connections to LM Studio sometimes get killed during multi-minute Qwen
calls. `LMStudioClient.call_json` has **4-retry with exponential backoff**
(2/4/8/16s) on `ReadError`/`ConnectError`/`ReadTimeout`/`5xx`. Persistent
schema errors (4xx) are not retried.

### Segmentation under-segments long windows
Qwen sometimes returns 1 sugya for an 80-line window. That destroys the
structure pass (one giant LM call gets killed by connection drop).

Two fixes in place:
1. **Segmentation retry** (`segment.py`): if <2 sugyot for ≥40 lines, retry with
   an explicit opener-formula checklist ("תנו רבנן", "אמר רב", "תנן", "איבעיא
   להו", etc.).
2. **Structure-pass chunking** (`window_orchestrator.py`): if any sugya is >25
   lines, split into chunks for the structure call so the LM doesn't have to
   generate a runaway response.

### Meforshim sourceRef matching
Sefaria returns commentaries with refs like `"Rashi on Bava Metzia 2a:1:1"`.
The LM sometimes returns shortened refs like `"Bava Metzia 2a:1:1"` (drops
"Rashi on "). Without tolerant matching, the verbatim Hebrew is lost from
the output and takeaways look like fabrication.

Fix in `meforshim.py:_assemble`: lookup tries exact, then strips known
prefixes ("Rashi on ", "Tosafot on ", ...), then falls back to suffix match.
Entries that still don't match get dropped (no point showing a takeaway with
no verbatim text behind it).

## Quality rules baked into prompts

Apply across all passes (`structure.py`, `teaching.py`, `meforshim.py`,
`translate.py`):
- **No transliteration**: write `מציאה`, `קַל וָחוֹמֶר`, `רבי יוחנן` — never
  "Mitzkayah" / "Kal V'chomer" / "Rabbi Yochanan". Includes titles, summaries,
  key terms, masechet names. Concrete examples in each prompt's system message.
- **Granularity**: each קשיא is its own step. Each תירוץ. No bundling.
- **No duplicate steps**: same line range = same step. The window orchestrator
  also post-processes to dedupe consecutive identical-range steps.
- **Sub-fields dropped**: the conditional kashya*/terutz*/raaya*/etc. fields
  were removed from the LM-facing schema. The classification is preserved on
  `hebrewStepName`. ~39% token savings.

## File layout

```
.
├── public/data/                    # JSON outputs (one per amud) + index.json
├── src/                            # React PWA
│   ├── components/                 # StepCard, MeforshimBlock, PhraseTable, etc.
│   └── lib/schema.ts               # TS-side Zod schema (matches py/schema.py)
└── py/                             # Local Python pipeline
    ├── schema.py                   # Pydantic mirror of schema.ts
    ├── llm.py                      # LM Studio client (strict json_schema)
    ├── sefaria.py                  # Sefaria fetcher (deterministic)
    ├── build.py                    # Single-amud entry point
    ├── window_orchestrator.py      # 5-amud window pipeline (the real one)
    ├── batch_masechet.py           # Detached batch driver
    ├── update_index.py             # Rebuilds public/data/index.json
    ├── postprocess_overviews.py    # Backfills per-amud mainTopic + overview
    └── passes/
        ├── segment.py
        ├── structure.py
        ├── phrasemap.py            # deterministic, no AI
        ├── translate.py            # LM aligns Sefaria EN to phrase split
        ├── meforshim.py
        ├── teaching.py
        └── validate.py             # currently skipped in batch
```

## Batch operations

- **Manifest**: `public/data/_batch_manifest.json` tracks per-window status.
- **Logs**: `public/data/_batch_log.txt` (human-readable) +
  `public/data/_batch_stdout.log` (raw stdout, per-pass detail).
- **Index watcher**: a separate PowerShell process rebuilds `index.json` every
  60s (so the PWA Library auto-updates as windows finish). Also runs
  `postprocess_overviews.py` to backfill per-amud overviews on any new files.
- **Resume**: re-run `batch_masechet.py Bava_Metzia` — windows whose JSONs all
  exist are skipped.

## Frontend contract (don't break this)

The PWA at `public/index.html` reads:
- `/data/index.json` — `{ entries: [{ ref, file, mainTopic, ...}] }`
- `/data/{Masechet}_{daf}{amud}.json` — `DafAnalysis` (per `src/lib/schema.ts`)

`DafAnalysis` shape MUST match `src/lib/schema.ts` exactly. The Python
`schema.py` is a mirror; the Pydantic models and Zod models must stay in sync.
Test round-trip with:

```python
from schema import DafAnalysis
DafAnalysis.model_validate(json.load(open("Bava_Metzia_2a.json")))
```
