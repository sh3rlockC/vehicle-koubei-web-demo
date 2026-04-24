# Vehicle Koubei Web Demo

Minimal Next.js app skeleton for the vehicle koubei demo flow:

- `/passphrase`
- `/vehicle`
- `/candidates`
- `/progress`
- `/result`

The app proxies `/api/*` to the backend origin configured by `BACKEND_ORIGIN` and uses
`sessionStorage` only for route continuity.

## Run

```bash
cd apps/web
npm install
npm run dev
```

If the API is not on `http://localhost:8000`, set:

```bash
export BACKEND_ORIGIN="http://your-api-host:8000"
npm run dev
```

## Notes

- The browser talks to the backend through a Next rewrite, so cookies stay on the same origin.
- Each step can be accessed directly, but missing prerequisite state shows a guard card and a link back to the previous step.
