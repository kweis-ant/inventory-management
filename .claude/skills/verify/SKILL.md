---
name: verify
description: How to build, launch and drive this app to observe a change end-to-end (FastAPI on 8001, Vite on 3000). Use before committing product changes.
---

# Verify a change in this app

## Launch (host network namespace)

Sandboxed shell commands run in an isolated network namespace and their child processes are stopped when the command ends. Start the servers **outside the sandbox** (`dangerouslyDisableSandbox: true`) and detached, then also curl them outside the sandbox:

```bash
cd server && (lsof -ti:8001 -sTCP:LISTEN | xargs -r kill); setsid nohup uv run python main.py > /tmp/backend.log 2>&1 < /dev/null & disown
cd client && (lsof -ti:3000 -sTCP:LISTEN | xargs -r kill); setsid nohup npm run dev > /tmp/frontend.log 2>&1 < /dev/null & disown
curl -s -o /dev/null -w "%{http_code}\n" localhost:8001/docs      # 200
curl -s -o /dev/null -w "%{http_code}\n" localhost:3000/          # 200
```

Uvicorn runs without reload: restart the backend after editing `server/*.py`. Vite hot-reloads `client/src`.

## Drive

- API surface: `curl localhost:8001/api/...` (see `server/main.py` routes; `?warehouse=&category=&status=&month=` filters, `all` = no filter).
- Frontend: no browser is installed in this container (Playwright and the built-in browser cannot launch). Confirm the route serves (`curl localhost:3000/<route>` → 200) and that the compiled view module contains the new template keys (`curl localhost:3000/src/views/X.vue | grep ...`); `cd client && npx vite build` catches template/compile errors. Visual checks must be done by the user at http://localhost:3000.

## Flows worth driving

- Filters: `/api/orders?warehouse=Tokyo&month=Q3-2025`, `/api/dashboard/summary?...`
- Restocking: `GET /api/restock/recommendations?budget=25000[&warehouse=Tokyo]` → `POST /api/restock/orders {"budget":..,"items":[{"sku","quantity"}]}` → `GET /api/restock/orders` (newest first). Probes: over-budget (400), unknown SKU (400), quantity 0 / empty items (422).
