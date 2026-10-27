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

## Where AI tools helped and misled

- **Helped:** mapped my Round 1 services to screens, wrote the first React views, and a browser script that clicks the whole flow.
- **Misled:** I got stuck on the refund API. The AI assumed the refund transaction sits on the order, but the mock returns it as `order.refunds[].transactions`. I printed the real JSON, gave it that exact payload, and then it was right.
- It also ran against the real Shopify store because `SHOPIFY_SHOP` was set in my shell (now forced to the mock), and picked a test customer with no valid Rx.
- Lesson: paste real responses, and trust nothing until it has run against the mock.
