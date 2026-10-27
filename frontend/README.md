# Eluno till: frontend (Next.js 16, App Router, TypeScript)

```bash
npm install
npm run dev            # http://localhost:3000, expects the API on BACKEND_URL (default http://127.0.0.1:8000)
npm run lint && npm run typecheck
npm run build && npm start          # production (standalone server)
npm run e2e            # browser tests against a running stack, see e2e/smoke.mjs
```

Environment (server side only, never sent to the browser):

| Variable | Purpose |
|---|---|
| `BACKEND_URL` | where the Python till API runs (default `http://127.0.0.1:8000`) |
| `ELUNO_API_TOKEN` | optional shared secret sent to the API as `X-Api-Token` |
| `ELUNO_UI_PASSWORD` | optional HTTP Basic password for the whole app (`proxy.ts`) |

The browser only talks to this app: `app/api/[...path]/route.ts` proxies to the API.
