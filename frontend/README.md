# Dispute intake frontend

React + TypeScript (Vite) client for the dispute-intake API. Three views: a demo Login (test personas), the customer Chat (Spanish or Portuguese) and the English HITL Console for agents. No UI library, no router library, one stylesheet.

## Requirements

Node 20 or newer and npm. The API must run on port 8000 (from the repo root: `uv run uvicorn src.api.app:app --reload --port 8000`).

## Development

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server proxies every `/api/...` request to `http://localhost:8000` (see `server.proxy` in `vite.config.ts`), so the app only uses relative URLs and never hardcodes a host.

Login is the local test issuer (`GET /api/v1/auth/personas`, `POST /api/v1/auth/test-session`), which the API exposes only when `APP_ENV` is `development` or `test`. Customer personas open the Chat; the agent button (customer id `AGENT-1`) opens the Console. The token lives in memory and in `sessionStorage`, so a page refresh keeps the session and a 401 sends you back to Login.

## Build

```bash
cd frontend
npm run build
```

`tsc -b` type-checks first, then Vite writes the static bundle to `frontend/dist/` (index.html plus hashed assets). `npm run preview` serves that folder locally if you want to inspect it without the API.

## How FastAPI serves the build

`src/api/app.py` mounts `frontend/dist` at `/` with `StaticFiles(html=True)` when that directory exists, so one process on port 8000 serves both the API under `/api/v1/...` and the UI at `/`. Build the frontend, then start the API and open http://localhost:8000. If `frontend/dist` is missing, the API runs without the UI.

Both `frontend/node_modules/` and `frontend/dist/` are git-ignored (root `.gitignore` plus `frontend/.gitignore`), so the build is a deployment step, not a committed artifact.

## Files

- `src/api.ts`: TypeScript types for every response and a `fetch` wrapper that adds the bearer token, parses the API `detail` message and reports 401s.
- `src/App.tsx`: state-based routing between Login, Chat and Console.
- `src/Login.tsx`: personas list and agent entry.
- `src/Chat.tsx`: language toggle (sent when the conversation starts), message list, candidate buttons that send the option number, lock confirmation buttons ("Sí" / "Sim" and "No" / "Não"), status line.
- `src/Console.tsx`: Cases (credit-candidate filter, Approve / Reject), Handoffs (open first, expandable packet, Resolve), Locks, Audit log (newest first, conversation filter). A 403 shows "This view requires the agent role".
- `src/styles.css`: neutral light theme, system font stack, 16px side gutters, phone width without horizontal scroll.
