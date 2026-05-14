# HANDOFF — Gemara Clarity (live state)

> 🆕 **REPO MOVED 2026-05-14.** The project was extracted from
> `C:\Users\DavidSherize_dd1jhqb\Downloads\GC\v2\` into its own GitHub repo at
> `C:\github\gemara-clarity\`. All paths in this file are now repo-relative.
> The old location can be deleted whenever the user wants. Open Claude from
> the new repo root.
>
> **Purpose:** This file is the live state of the project. It exists so the
> user can clear the Claude chat between sessions without losing context. Any
> new Claude opening this repo reads this first, then `CLAUDE.md`, then dives
> in. Memory entries at `~/.claude/projects/C--github-gemara-clarity/memory/`
> carry the durable learnings.
>
> **Update cadence:** rewrite this file at the end of each working session, or
> whenever the user says "handoff" / "clear chat" / "fresh chat". Keep it
> SHORT and CURRENT. Stale facts here cost the next Claude hours.

---

## 1. What this project is (one paragraph)

A local-first Talmud teaching-sheet pipeline. Python orchestrator (`py/`)
fetches Gemara from Sefaria, runs it through Qwen 3.6 27B on LM Studio over the
LAN (`http://10.6.15.101:1234`), produces per-amud JSON analyses at
`public/data/`. A React PWA (`src/`) renders them with full Hebrew
script, phrase-aligned translations, classification of every step
(מימרא/קשיא/תירוץ/etc.), meforshim takeaways, and an active-learning feedback
loop. **Zero cloud LLM calls. All inference local on a 192GB Mac Studio.**

The user is running on **Windows + Python 3.13** locally; LM Studio is on the
Mac Studio at `10.6.15.101:1234`.

---

## 2. What's actively running (PIDs and ports)

🛑 **PAUSED 2026-05-14T13:00Z.** Batch, feedback server, and index watcher were all stopped at a clean window boundary (right after window 28/48 finished writing). Vite (node) is still up. To resume, follow § 6.

| Process | PID | What | State |
|---|---|---|---|
| Main batch | (was 73804) | `batch_masechet.py Bava_Metzia` | **stopped** — was about to start w29/48 |
| Index watcher | (was 87968) | every 90s: postprocess_overviews + fix_sugya_step_bounds + update_index | **stopped** |
| Feedback server | (was 33320, port 5175) | receives PWA classification corrections → writes JSON + appends `_feedback.jsonl` | **stopped** |
| Vite dev server | port 5174 | the PWA — `npm run dev` at repo root | **stopped** (killed during repo move 2026-05-14; run `npm install && npm run dev` to bring it back) |
| LM Studio (Mac) | n/a | Qwen 3.6 27B loaded with n_ctx ≥ 128k and eval_batch_size ≥ 8192 | manual on the Mac |

Logs:
- `public/data/_batch_log.txt` — high-level batch events (window starts, failures, ETAs)
- `public/data/_batch_stdout.log` — detailed per-pass output
- `public/data/_feedback.jsonl` — user corrections (training data for future LoRA)

---

## 3. Current corpus state

- **Bava Metzia**: **130 amudim on disk** as of pause (2026-05-14T13:00Z). Batch completed through **window 28/48 inclusive** (last built: 69b-71b). Next window queued is **w29/48 (72a-74a)** — when you resume, batch_masechet.py will skip everything already on disk and pick up there. True steady-state pace is ~80m/window per the perf audit (the displayed "44.8m/window avg" is still converging upward from the 12 skipped windows at run start).
- **Two failed windows pending retry** — `_batch_manifest.json` is authoritative:
  - **w12/48 (29b-31b)** failed early on `ReadError: [WinError 10054]` (4-retry exhaustion on long Qwen call). 5 amudim missing.
  - **w22/48 (54b-56b)** failed 2026-05-14T05:39Z on segmentation non-JSON. 5 amudim missing.
  - Total **10 amudim absent**. `batch_masechet.py` auto-retries at end of pass (2 rounds, default). The `llm.py` hardening (this session) should let w22 succeed on retry. If w12 fails again, bump `max_attempts` 4 → 8 in `llm.py` for long Qwen calls.
- **Berakhot**: wiped 2026-05-14, will rebuild later.
- **All other masechtos**: not yet started.

Check progress:
```
ls public/data/ | grep "^Bava_Metzia_" | wc -l    # count built BM amudim
tail public/data/_batch_log.txt                   # last events
```

---

## 4. Pipeline architecture (one diagram, one set of facts)

```
Sefaria fetch (deterministic) ──┐
                                ├─→ Pass 1: segment (Qwen) — sugya boundaries
                                ├─→ Pass 2: structure (Qwen) — step skeletons per sugya
                                ├─→ Pass 2.5a: source-check (deterministic regex on opener patterns)
                                ├─→ Pass 2.5b: verifier-in-loop (Qwen) + self-consistency on uncertain steps + Nemotron tiebreaker on three-way disagreements
                                ├─→ Pass 3a: phrase split (deterministic, punctuation-based)
                                ├─→ Pass 3b: phrase alignment (Qwen) — literal English aligned to Aramaic phrases
                                ├─→ Pass 4: meforshim grounding (Qwen) — Rashi/Tosafot takeaways from verbatim Hebrew
                                └─→ Pass 5: teaching polish (Qwen) — tighten prose, add nikud
                                            ↓
                                            Split per amud → write JSONs
                                            Checkpoint after each pass → resume on restart
```

- Windows = **5 consecutive amudim** so sugyot span amud boundaries (`_split_to_amud_jsons` handles the cross-amud marker `(continues)`).
- 100% Qwen 3.6 27B except deterministic passes.
- Model routing constants are in `py/llm.py:PASS_MODEL` — DO NOT switch back to Gemma here unless you've re-tested (Gemma under-segmented multi-amud windows).
- Schema is mirrored TS↔Python: `src/lib/schema.ts` and `py/schema.py` MUST stay in sync.

---

## 5. Active learning loop

User clicks a step's classification badge in the PWA → dropdown → pick correct label → POST to `/api/feedback` (proxied to `localhost:5175`) → feedback server (a) applies correction in-place to the JSON, (b) appends a labeled training record to `_feedback.jsonl`. The jsonl file is the seed for an eventual LoRA fine-tune of Qwen (or Gemma) on the user's specific taste.

---

## 6. Common operations

### Resume after crash / reboot

```powershell
# 1. Start LM Studio with Qwen 3.6 27B loaded (manual on the Mac)
# 2. From the Windows side:
cd "C:\github\gemara-clarity\py"
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUNBUFFERED="1"

# Batch
Start-Process py "-u","batch_masechet.py","Bava_Metzia" `
  -RedirectStandardOutput "..\public\data\_batch_stdout.log" `
  -RedirectStandardError "..\public\data\_batch_stderr.log" `
  -WindowStyle Hidden

# Index watcher
Start-Process pwsh -ArgumentList "-NoProfile","-File","_index_watcher.ps1" -WindowStyle Hidden

# Feedback server
Start-Process py "-u","feedback_server.py" `
  -RedirectStandardOutput "..\public\data\_feedback_server.log" `
  -RedirectStandardError "..\public\data\_feedback_server.err" `
  -WindowStyle Hidden

# PWA
cd ..
npm run dev   # port 5174
```

The batch is **resumable** — it skips any window whose 5 amud JSONs already exist. The window orchestrator also has a "polished" checkpoint fast-path: if a window crashed AFTER all LM passes but BEFORE writing files, restart re-uses the saved state.

### Post-batch cleanup (when batch finishes)

```
cd py
py fixup_all.py
```
That runs: index rebuild → overview backfill → heuristic audit → LM verifier sweep → title cleanup → final audit. Takes ~6-10 hours; non-destructive.

### Pause everything cleanly

```powershell
Get-Process -Name py -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process -Name pwsh -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -eq "" } | Stop-Process -Force
```

---

## 6.5. WHERE TO FIND EVERYTHING (the durable assets)

Every prompt, script, and correction is on disk. Nothing important lives only in chat memory.

### Pipeline scripts (`py/`)

| File | Purpose | When to run |
|---|---|---|
| `build.py` | Build ONE amud through all 6 passes. Mostly for testing. | `py build.py Bava_Metzia 5a` |
| `window_orchestrator.py` | Build a 5-amud window. Where the in-pipeline logic lives. | called by batch |
| `batch_masechet.py` | Drives the whole tractate, window by window, with retry passes. | `py batch_masechet.py Bava_Metzia` |
| `llm.py` | LM Studio client. Strict json_schema mode, retry/backoff, model reload handling, self-consistency support. **THIS is where PASS_MODEL routing lives.** | imported |
| `schema.py` | Pydantic schema — must stay byte-compatible with `src/lib/schema.ts`. | imported |
| `sefaria.py` | Sefaria.org fetchers. Community + Sefaria + William Davidson EN merge. | imported |
| **`passes/segment.py`** | Pass 1 prompt — sugya boundaries | prompt edits live here |
| **`passes/structure.py`** | Pass 2 prompt — step decomposition. **Worked-example few-shot for BM 2a is in here. ~1200 words. Don't strip it.** | prompt edits live here |
| **`passes/source_check.py`** | Pass 2.5a — deterministic regex pattern overrides (תא שמע, ואידך, וצריכא, …) | pattern edits here |
| **`passes/phrasemap.py`** | Pass 3a — deterministic phrase split on punctuation. No LM. | tuning here |
| **`passes/translate.py`** | Pass 3b prompt — phrase alignment (literal only + 2.5× guardrail) | prompt edits here |
| **`passes/meforshim.py`** | Pass 4 prompt — Rashi/Tosafot takeaways | prompt edits here |
| **`passes/teaching.py`** | Pass 5 prompt — polish + nikud rule | prompt edits here |
| **`passes/validate.py`** | Pass 6 prompt (verifier) | prompt edits here |
| `verify_classifications.py` | Standalone verifier pass + post-hoc sweep. Has self-consistency + Nemotron tiebreaker. | `py verify_classifications.py` |
| `postprocess_overviews.py` | Backfill per-amud mainTopic + overview from sugya boundaries (no LM) | called by watcher every 90s |
| `fix_sugya_step_bounds.py` | Recompute firstStepNumber/lastStepNumber per sugya (matches Aramaic content against Hebrew source) | called by watcher every 90s |
| `update_index.py` | Rebuild `_index.json` from JSON files | called by watcher every 90s |
| `retranslate_phrases.py` | Re-run translate pass with skip-already-literal heuristic | one-shot post-process |
| `translate_meforshim.py` | Phrase-align Rashi/Tosafot verbatim text. Adds `phrases[]` field. | one-shot post-process |
| `add_nikud.py` | Add vowels to bare Hebrew keyTerms via Qwen | one-shot post-process |
| `fix_titles.py` | Replace transliterated terms in titles with Hebrew script | one-shot post-process |
| `audit_classifications.py` | Heuristic auditor — flags suspicious labels without LM | `py audit_classifications.py` |
| `fixup_all.py` | Orchestrator that runs every post-batch cleanup in order | run after batch finishes |
| `feedback_server.py` | HTTP server on port 5175 — receives PWA corrections | runs continuously |
| `_index_watcher.ps1` | Loop: every 90s run postprocess + bounds + index | runs continuously |

### Frontend (`src/`)

| Path | What it is |
|---|---|
| `App.tsx` | Top-level — wires QuickPicker, SearchPanel, ArgumentFlow, StepCard, DafPicker |
| `lib/schema.ts` | Zod schema — must mirror `py/schema.py` |
| `lib/library.ts` | LibraryIndex loader |
| `components/QuickPicker.tsx` | Compact Masechet/Daf/a-b dropdown (replaced Library) |
| `components/StepCard.tsx` | Step card. **Inline classification edit → POST to /api/feedback** |
| `components/PhraseTable.tsx` | Aramaic/English phrase table |
| `components/MeforshimBlock.tsx` | Renders meforshim, **falls back gracefully to old block format if `phrases[]` absent** |
| `components/Search.tsx` | Full-tractate search |
| `components/ArgumentFlow.tsx` | Mermaid flow diagram per sugya |
| `components/SugyaDivider.tsx` | Sugya header + per-sugya "🖨 Print" button |
| `components/StepOutline.tsx` | Right-side sidebar — **has proportional-fallback if firstStepNumber bounds look stale** |
| `styles/global.css` | Includes hover-highlight table rules + `@media print` block |

### User corrections / training data

- `public/data/_feedback.jsonl` — each line: `{ts, ref, stepNumber, field, oldValue, newValue, applied, message}`. Seed for eventual LoRA fine-tune.

### Old `v1` project (`Downloads/Gemara Clarity.html`)

- Standalone single-file React-less PWA. Live at `gemara-clarity.netlify.app`.
- **Not being migrated** — user explicitly wants v1 to stay as-is for now. v2 is the new effort.
- Recent fix: dropdown shows all 37 Shas masechtos (was 4).

---

## 7. Recent work (last session) — for situational awareness

These are the most recent decisions and the user's reactions. If something here surprises a future Claude, double-check against the live files before acting.

1. **All passes use Qwen 27B** — not Gemma. (Switched 2026-05-13 after Gemma's segmentation under-segmented long windows.)
2. **Structure prompt has explicit BM 2a worked-example** — few-shot in-context. Don't strip examples; they raised classification accuracy substantially.
3. **`source_check.py` runs before the LM verifier** — pure regex overrides for high-confidence patterns ("תא שמע", "ואידך", "וצריכא", "לא דאמר ליה", etc.). Cheap, zero LM calls. See `passes/source_check.py`.
4. **Verifier has self-consistency**: when first verdict is uncertain, 2 more Qwen calls at temp 0.3 → majority vote. If still split → Nemotron tiebreaker (cross-family). See `verify_classifications.py:verify_steps_in_memory`.
5. **Meforshim verbatim text is phrase-aligned** — same Hebrew/English table format as the main daf phrases. Frontend renders this when `phrases` field is present on a `MeforeshComment`. Older JSONs without this field still render the old block format via fallback in `MeforshimBlock.tsx`.
6. **Feedback server is on port 5175**, Vite proxies `/api/feedback` to it. Both ports must be free.
7. **Library component removed**; `QuickPicker` (compact Masechet/Daf/a-b dropdown) is the navigation surface now.
8. **PDF export = browser print** with print CSS that hides chrome. Per-sugya print uses `data-print-include="true"` to filter.
9. **Argument-flow diagrams** — Mermaid was **replaced 2026-05-14** with a vertical indented tree in `src/components/ArgumentFlow.tsx`. Each step is one row: 3px color stripe (uses existing `--mimra`/`--kashya`/etc. CSS tokens) + `#N` + Hebrew name + truncated title. Depth indents on `branchRole === "opens_new_branch"`, outdents on `returns_to_previous_branch`, resets on `conclusion_of_branch`. Compact, on-theme, structural. The `mermaid` import is gone but the npm dep is still in `package.json` (run `npm uninstall mermaid` if you want it gone for real). Print CSS class renamed from `.argument-flow` → `.arg-flow`.
10. **Token-level highlighting** is a CSS-only `:hover` on `tbody tr`, not real token alignment.
11. **llm.py hardened 2026-05-14**: non-JSON model output now gets the same backoff retry (2/4/8/16s, 4 attempts) as empty content. Previously a single bad output killed the whole window pass — that's how window 22 died. Fix is live for any fresh `batch_masechet.py` / `window_orchestrator.py` invocation. Diagnostics this session showed the existing batch had **two** failed windows (12 + 22), so the retry pass at end-of-batch matters.
12. **Diagnostics ran 2026-05-14 (subagent fan-out, ~280k Claude tokens — user pushed back; see `memory/feedback_token_usage.md`). Summary:**
    - Classification audit: 32/1574 flagged (2.0%). Biggest signal: **15× שאלה after קשיא without intervening תירוץ** — likely follow-up קשיא mis-labeled. Worth a targeted fixup pass post-batch.
    - Perf "slowdown" was a rolling-average artifact. Steady state ~80m/window, perfectly correlated with step count (r=0.96).
    - Cross-amud sugya integrity: 91 cross-amud sugyot across 120 amudim, **zero orphans**. Invariant holds.
    - LM Studio + servers: all green. `gpt-oss-120b`, `hermes-4-70b` loaded but never used — safe to unload from LM Studio to reclaim VRAM. **Keep nemotron** (verifier tiebreaker).
    - Sefaria translation quality: 0.2% prose contamination. **BM 5a is the noisy outlier** (one 17.6× ratio phrase = pure Steinsaltz narrative leak). Target re-translate.
    - Zod round-trip: 120/120 pass, but **4 latent schema drifts**: `Step.phrases` Zod `min(1)` vs Pydantic `default=[]`; `CostBreakdown` Zod required vs Pydantic defaulted; Zod `.optional()` rejects `null` if Python ever emits it; Zod allows float for token counts where Pydantic is int. None fire today; fix when next in schema code.

---

## 8. Memory pointers (the durable knowledge)

Located at `~/.claude/projects/C--github-gemara-clarity/memory/` (copied 2026-05-14 from the old `C--Users-...-Downloads-GC` key when the repo moved out):

| File | What it covers |
|---|---|
| `MEMORY.md` | Index — always loaded automatically |
| `project_gemara_clarity.md` | What this project is, model routing |
| `user_role_david.md` | Collaboration style (autonomous mode, terse feedback, yeshiva background) |
| `gemara_quality_rules.md` | No transliteration / granularity / no fabricated meforshim |
| `talmud_classification_rules.md` | קשיא vs שאלה, תירוץ vs תשובה, וצריכא, with worked examples |
| `model_bakeoff_results.md` | Which local models work or fail for strict json_schema — don't re-test |
| `lm_studio_gotchas.md` | reasoning_content, n_ctx, WinError 10054 retry, etc. |
| `sefaria_gotchas.md` | Community vs William Davidson translation, amud-vs-daf counts, ref prefixes |
| `feedback_token_usage.md` | NEW 2026-05-14 — David is cost-sensitive on Claude API tokens. Don't fan out subagents speculatively. "Give it your all" = pipeline progress, not Claude compute. |

Update these when a new durable learning surfaces. Don't dump session state here — that goes in this HANDOFF.md.

---

## 9. Open items

These are real TODOs the user has acknowledged but hasn't done yet:

- [ ] **Resume the batch** when ready — `cd py; Start-Process py "-u","batch_masechet.py","Bava_Metzia" …` per § 6. Skips the 130 built amudim, picks up at w29/48 (72a-74a). Also restart index watcher + feedback server.
- [ ] Online deployment (Vercel for PWA + R2 for JSONs + serverless feedback function). User opened the door to this but hasn't committed.
- [ ] Full meforshim alignment sweep across all built amudim (only BM 5a done). Queue when batch finishes.
- [ ] LM verifier sweep across pre-verifier-in-loop amudim (first ~25 windows). Queue when batch finishes.
- [ ] **Targeted קשיא-vs-שאלה sweep** on the 15 audit hits (שאלה directly after קשיא without intervening תירוץ — almost certainly mis-labeled follow-up קשיא).
- [ ] **Spot-fix BM 5a translation** — Steinsaltz narrative leaked into one phrase at 17.6× length ratio.
- [ ] Consider bumping `llm.py` `max_attempts` 4 → 8 for the WinError-10054 path before resuming, if you want w12 retry to have a better chance.
- [ ] Eventually fine-tune Qwen (or Gemma) on `_feedback.jsonl` corrections.
- [ ] **Schema drift cleanup** — fix the 4 latent TS↔Python schema mismatches noted in § 7.12 next time you're in schema code.

---

## 10. Handoff procedure (for the user)

When the chat is getting long and you want to clear it:

1. Tell Claude "handoff" or "update HANDOFF and clear chat".
2. Claude updates this file with the live state — what's running, what just happened.
3. Claude updates any memory entries that have new durable info.
4. You clear the chat.
5. New Claude session opens, reads HANDOFF.md + CLAUDE.md + memory, picks up.

This file is the rolling state. The other files (`CLAUDE.md`, memory) are the durable knowledge. Together they're a complete project handoff.
