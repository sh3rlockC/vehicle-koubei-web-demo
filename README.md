# Vehicle Koubei Web Demo

Single-server orchestration app for the vehicle koubei workflow.

This app provides:

- external Web access with weekly passphrase gating
- vehicle candidate resolution and confirmation
- async job orchestration for the current koubei toolchain
- online result pages
- AI one-page reporting
- grounded QA on top of completed job results

MVP dependency rule:

- keep the six existing repos in place
- call them through stable wrappers
- do not block the MVP on repo restructuring

Current external dependencies:

- `data/repos/vehicle-id-finder`
- `data/repos/auto-koubei-collector`
- `data/repos/dcd-koubei-collector`
- `data/repos/koubei-postprocess`
- `data/repos/koubei-keyword-summary-skill`
- `koubei-wordcloud`

## Local Docker Run

The Docker setup expects the whole workspace to be mounted as `WORKSPACE_ROOT`, so the
existing skill repos remain available without restructuring.

```bash
cd /Users/xyc/Documents/codexwork/vehicle-koubei-web-demo
cp .env.example .env
docker compose up --build
```

Default local passphrase in `.env.example`:

- `weekly-secret`

Important runtime note:

- the worker can start inside Docker, but the Autohome collector still depends on the external
  `agent-browser` CLI
- if `agent-browser` is not present in the worker image/runtime, Autohome collection jobs will fail
- the current compose setup logs this as a warning instead of pretending the dependency is solved
