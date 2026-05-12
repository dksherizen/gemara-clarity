# Gemara Clarity v2

A complete rebuild of [gemara-clarity.netlify.app](https://gemara-clarity.netlify.app/) — single-file PWA → proper TypeScript app with a 6-pass LLM pipeline, real meforshim grounding from Sefaria, hybrid local/cloud model routing, and a static-JSON cache that lets users browse pre-computed dapim with zero API costs.

---

## Why v2

The original is a 2,209-line HTML file that sends 4-line text chunks to OpenAI with a single mega-prompt doing segmentation + classification + translation + teaching in one shot. It has no awareness of meforshim and only re-prompts when literal source-token coverage drops below 85%.

v2:

- **Splits the work** into 6 specialized passes so each piece runs at the right intelligence level.
- **Grounds analysis** in actual Sefaria-fetched Rashi / Tosafot / Rishonim text instead of model recall.
- **Routes each pass** to the right model — frontier (Claude Opus 4.7 / GPT-5 / Gemini 2.5 Pro) for judgment work, local LM Studio for mechanical work.
- **No more 4-line chunking** — pass 1 reads the entire amud at once and finds natural sugya boundaries; pass 2 processes one full sugya at a time.
- **Cross-model validation** — a different frontier model re-reads the final analysis to catch the wrong classifications a single-model pass would miss.

---

## The 6-pass pipeline

| # | Pass | Job | Default provider |
|---|---|---|---|
| 1 | Segmentation | Read whole daf → identify natural sugya boundaries. | Anthropic (Opus 4.7) |
| 2 | Structure | Per-sugya → break into argumentative steps + classify (מימרא/קשיא/תירוץ/…) with confidence + dependencies. | Anthropic |
| 3 | Phrase mapping | Per-step → Aramaic ↔ English phrase tables with ≥85% source coverage check. | LM Studio (local) |
| 4 | **Meforshim grounding** | Per-step → fetch verbatim Rashi/Tosafot/Rishonim from Sefaria, summarize each + interplay. | Anthropic |
| 5 | Teaching polish | Tighten whatsHappening / deeperAnalysis to length limits, dedupe terms, add nikud. | LM Studio |
| 6 | Validation re-read | Different frontier model audits the analysis vs. source for wrong classifications, missing coverage, hallucinated meforshim. Auto-patches what it can. | OpenAI |

Per-pass routing is overridable via `PASS_<NAME>_PROVIDER` env vars.

---

## Project layout

```
v2/
├── index.html, vite.config.ts, tsconfig.json, package.json
├── .env.example, .gitignore, README.md
├── src/
│   ├── main.tsx, App.tsx
│   ├── styles/global.css           # Lifted from original + new meforshim styling
│   ├── components/
│   │   ├── Header.tsx, Controls.tsx, Library.tsx
│   │   ├── MetaCard.tsx, SugyaDivider.tsx
│   │   ├── StepCard.tsx, PhraseTable.tsx
│   │   ├── KeyTermsBox.tsx, MeforshimBlock.tsx, LogicalBreakdown.tsx
│   └── lib/
│       ├── schema.ts               # Zod types — single source of truth
│       ├── library.ts              # Loads /data/*.json
│       ├── sefaria/client.ts       # Sefaria daf text + meforshim links + verbatim text
│       └── llm/
│           ├── router.ts, types.ts, jsonparse.ts
│           ├── anthropic.ts, openai.ts, google.ts   # OpenAI adapter also drives LM Studio
│       └── pipeline/
│           ├── 1-segmentation.ts, 2-structure.ts, 3-phrasemap.ts
│           ├── 4-meforshim.ts, 5-teaching.ts, 6-validate.ts
│           └── orchestrator.ts
├── scripts/
│   ├── process-daf.ts              # Run pipeline on one daf → public/data/{ref}.json
│   ├── batch-tractate.ts           # Process whole masechet, update index, resume on failure
│   └── compare-vs-original.ts      # A/B metrics: original vs. new pipeline
└── public/data/
    ├── index.json                  # Library index — what's been processed
    └── Berakhot_2a.demo.json       # Hand-written fixture so the UI works out of the box
```

---

## Setup

```powershell
cd v2
npm install
copy .env.example .env
```

Then edit `.env` and set at least one provider:

```
ANTHROPIC_API_KEY=sk-ant-...
# Optional: also point at your Mac running LM Studio
LMSTUDIO_BASE_URL=http://<mac-lan-ip>:1234/v1
LMSTUDIO_MODEL=qwen2.5-72b-instruct
```

---

## Usage

### Browse the UI

```powershell
npm run dev
```

Open the URL Vite prints (defaults to `http://127.0.0.1:5174/`). The demo fixture loads automatically. Generated dapim from the CLI will appear in the Library panel.

### Process one daf

```powershell
node --env-file=.env --import tsx scripts/process-daf.ts -m Berakhot -d 2 -a a
```

Flags: `--no-meforshim` skips pass 4 for faster/cheaper runs. Output lands in `public/data/{Masechet}_{daf}{amud}.json`.

### Process a whole tractate (resumable)

```powershell
node --env-file=.env --import tsx scripts/batch-tractate.ts -m Berakhot --from 2 --to 5 --delay 1000
```

Skips dapim that already exist in `public/data/`. Updates `index.json` after each one so the UI sees results live. Use `--retry 3` to retry transient failures.

### A/B compare vs. original output

```powershell
node --env-file=.env --import tsx scripts/compare-vs-original.ts `
  --original ./oldfile.json `
  --next ./public/data/Berakhot_2a.json `
  -m Berakhot -d 2 -a a
```

Prints structured metrics — step counts, classifications, phrase coverage vs. Sefaria source text, key-term nikud rate, redundancy, meforshim presence, low-confidence steps, etc. Stars mark categories where the new pipeline beats the original.

### Production build

```powershell
npm run build
```

Outputs static `dist/` ready for any host. Bundle: ~265 KB JS / ~80 KB gzipped.

---

## Configuration (.env)

```
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GOOGLE_API_KEY=

# LM Studio (OpenAI-compatible)
LMSTUDIO_BASE_URL=http://localhost:1234/v1
LMSTUDIO_MODEL=qwen2.5-72b-instruct

# Override which provider handles each pass
PASS_SEGMENTATION_PROVIDER=anthropic
PASS_STRUCTURE_PROVIDER=anthropic
PASS_PHRASEMAP_PROVIDER=lmstudio
PASS_MEFORSHIM_PROVIDER=anthropic
PASS_TEACHING_PROVIDER=lmstudio
PASS_VALIDATE_PROVIDER=openai

# Per-provider model overrides (optional)
ANTHROPIC_MODEL=claude-opus-4-7
OPENAI_MODEL=gpt-5
GOOGLE_MODEL=gemini-2.5-pro
```

---

## Status

- [x] Project scaffold (Vite + TS + React 19)
- [x] Sefaria client — text, links, verbatim commentary
- [x] LLM router — Anthropic / OpenAI / Gemini / LM Studio
- [x] Pass 1: sugya segmentation
- [x] Pass 2: structural skeleton (per-sugya, classified steps)
- [x] Pass 3: phrase mapping with coverage validation + retry
- [x] Pass 4: meforshim grounding (verbatim Sefaria text → structured takeaways)
- [x] Pass 5: teaching-layer polish (length, nikud, dedupe)
- [x] Pass 6: cross-model validation re-read with auto-patches
- [x] React UI port (preserves original visual design, adds meforshim block + sugya dividers)
- [x] CLI: process one daf
- [x] CLI: batch a whole tractate, resumable, with live index
- [x] CLI: A/B compare vs. original output with structured metrics
- [x] Static-JSON cache served via `public/data/`
- [x] Print/PDF CSS preserved from original
- [x] Demo fixture so UI works before any pipeline run

### Open

- Actual end-to-end run against your API keys + LM Studio is your next step — the harness is ready, it just needs credentials.
- IndexedDB cache on the UI side (currently re-fetches from `/data/` each load — fine for static JSON but could be tightened).
- Compare run output once you have one: `npm-style` script wiring (`npm run process-daf -- ...`) — works today but I left them in `node --env-file --import tsx` form for clarity.
