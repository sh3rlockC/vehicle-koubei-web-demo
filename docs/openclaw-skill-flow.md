# OpenClaw Koubei Skill Flow

## Installed Skills

All six koubei skills are installed in the dedicated `koubei` OpenClaw workspace:

- `vehicle-id-finder`: resolve Autohome and Dongchedi series IDs from a vehicle name.
- `auto-koubei-collector`: collect Autohome koubei and write Excel, validation JSON, and progress JSON.
- `dcd-koubei-collector`: collect Dongchedi koubei and write Excel, validation JSON, failed-pages JSON, and progress JSON.
- `koubei-postprocess`: merge and normalize Autohome and Dongchedi raw outputs.
- `koubei-keyword-summary`: generate dual-platform keyword summary and one-page Excel sheet.
- `koubei-wordcloud`: generate positive/negative wordcloud images and term-list Excel.

OpenClaw workspace path:

```text
/Users/xyc/Documents/codexwork/openclaw-koubei-runtime/workspace/skills
```

Configured local OpenClaw agents:

- `main`: default fallback agent.
- `autohome`: Autohome collection agent.
- `dongchedi`: Dongchedi collection agent.

`autohome` and `dongchedi` keep separate session stores for concurrency, but their `auth-profiles.json`, `auth-state.json`, and `models.json` are synced from the original `main` agent. The runtime workspace `BOOTSTRAP.md` must be absent in production collection mode; otherwise new agent sessions can be intercepted by the first-run bootstrap flow instead of executing the collector skill.

## Runtime Ownership

The Web Demo keeps one pipeline owner:

- API owns passphrase access, vehicle candidate confirmation, job creation, result reads, and AI report endpoints.
- Worker owns queue execution, stage order, database status, progress aggregation, logs, degraded handling, and artifact validation.
- OpenClaw owns agent-executed skill stages only when a stage is listed in `OPENCLAW_ADAPTER_STAGES`.
- The dedicated `koubei` OpenClaw profile currently uses `minimax-portal/MiniMax-M2.7` as its default agent model.
- Collection is routed to two stage-specific OpenClaw agents: `autohome` only handles Autohome, and `dongchedi` only handles Dongchedi.

Current local setting:

```text
OPENCLAW_ADAPTER_ENABLED=true
OPENCLAW_ADAPTER_STAGES=collecting_autohome,collecting_dcd
OPENCLAW_AUTOHOME_AGENT_ID=autohome
OPENCLAW_DCD_AGENT_ID=dongchedi
```

This means both collection stages run through OpenClaw. Postprocess, summary, wordcloud, and AI report still run in the worker/API process.

## End-To-End Flow

1. User enters a vehicle name in the Web UI.
2. API resolves candidate vehicle IDs.
   Current app route still calls the resolver script from the API container. `vehicle-id-finder` is installed in OpenClaw for the next routing step, but API-to-OpenClaw vehicle resolution is not wired yet.
3. User confirms Autohome and Dongchedi candidates.
4. API creates a job and enqueues worker execution.
5. Worker builds stage commands and routes configured collection stages through OpenClaw.
6. Worker submits `collecting_autohome` to OpenClaw `agent_id=autohome`, which runs `auto-koubei-collector`.
7. Worker submits `collecting_dcd` to OpenClaw `agent_id=dongchedi`, which runs `dcd-koubei-collector`.
8. Worker waits for expected artifacts from both collectors.
9. Worker runs `koubei-postprocess` locally to create the dual-platform workbook.
10. Worker runs `koubei-keyword-summary` locally to create the summary Excel and validation JSON.
11. Worker runs `koubei-wordcloud` locally to create wordcloud PNGs and term-list Excel.
12. API assembles result assets and generates the deterministic or LLM-backed one-page AI report.

During collection, the progress API reads `collecting_autohome.progress.json` and `collecting_dcd.progress.json` and exposes each collector's `progress_percent` and `progress_message` to the Web UI. The progress page renders separate 0-100 bars for Autohome and Dongchedi.

## Web Demo LLM Configuration

The local Web Demo API LLM is separate from the OpenClaw agent model. The API one-page report is now configured to use DeepSeek V4 through the OpenAI-compatible chat completions API:

```text
LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL_REPORT=deepseek-v4-flash
LLM_MODEL_QA=deepseek-v4-flash
```

The API service uses `HTTPReportLLMClient` and calls `/chat/completions` when `LLM_PROVIDER=deepseek`. It also enables OpenAI-style JSON response format for DeepSeek to reduce invalid JSON fallback. If the provider still fails or returns invalid JSON, the one-page report falls back to the deterministic local report.

The result QA path also uses the same DeepSeek-compatible client through `LLM_MODEL_QA`. It first retrieves relevant chunks from the current summary workbook and AI report, then asks the model to generate a Chinese answer from those chunks only. If the QA model is unavailable or returns an empty answer, the API falls back to the deterministic rule-based answer. The API response keeps `citations` empty so the Web UI does not show source evidence.

OpenClaw itself now uses MiniMax Token Plan for agent-executed collection stages:

```text
provider=minimax-portal
model=MiniMax-M2.7
baseUrl=https://api.minimaxi.com/anthropic/v1
```

## Artifact Contracts

`collecting_autohome` must produce:

- Autohome raw Excel.
- Same-name `.validation.json`.
- `collecting_autohome.progress.json`.

`collecting_dcd` must produce:

- Dongchedi raw Excel.
- Same-name `.validation.json`.
- `collecting_dcd.progress.json`.
- Same-name `.failed-pages.json` when failures exist; an empty array is acceptable when no pages fail.

Worker validates the files after OpenClaw returns or accepts the job. OpenClaw must not change these paths or invent different output names.

## OpenClaw Stage Routing

OpenClaw is a stage adapter, not a second orchestrator.

- Add a stage to `OPENCLAW_ADAPTER_STAGES` only when its output contract is stable.
- Remove a stage from `OPENCLAW_ADAPTER_STAGES` to fall back to the local worker runner.
- Route `collecting_autohome` with `OPENCLAW_AUTOHOME_AGENT_ID`; route `collecting_dcd` with `OPENCLAW_DCD_AGENT_ID`.
- If a stage-specific agent ID is unset, the worker falls back to `OPENCLAW_AGENT_ID`.
- Keep postprocess, summary, wordcloud, and AI report local until there is a reason to move them.
- Mount OpenClaw state read-only and set `OPENCLAW_TASK_DB_PATH` so the worker can fail fast when an accepted OpenClaw task changes to `failed`, `timed_out`, `cancelled`, or `lost`.

## Installed Dependency Notes

- `agent-browser` is available on the host, but the current Autohome production flow primarily uses direct API/detail-page extraction instead of browser-dialog collection.
- Python dependencies verified on host: `requests`, `openpyxl`, `pandas`, `wordcloud`, `jieba`, `matplotlib`, `PIL`, `yaml`.
- Node dependency for `vehicle-id-finder`: `playwright` is installed locally under the OpenClaw `vehicle-id-finder` skill directory.
- Playwright Chromium runtime is installed in the user cache.
- Worker container includes `fonts-noto-cjk`; wordcloud generation passes `/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc` through `--font-path`.

## Next Upgrade

Wire API vehicle resolution to OpenClaw `vehicle-id-finder` if we want the first step to be agent-managed too. Until then, OpenClaw is active for both collection stages only.
