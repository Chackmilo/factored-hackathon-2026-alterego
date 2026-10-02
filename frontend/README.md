# Dispute intake frontend

React + TypeScript (Vite) client for the dispute-intake API. Three views: a Login (Supabase Auth, or demo test personas), the customer Chat (Spanish or Portuguese) and the English HITL Console for agents. No UI library, no router library, one stylesheet.

## Requirements

Node 22 or newer and npm (`@supabase/supabase-js` 2.117.2 declares Node 22; CI and the Docker build use Node 22). The API must run on port 8000 (from the repo root: `uv run uvicorn src.api.app:app --reload --port 8000`).

## Development

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server proxies every `/api/...` request to `http://localhost:8000` (see `server.proxy` in `vite.config.ts`), so the app only uses relative URLs and never hardcodes a host.

## Sign-in

Login has two modes, picked by what the build carries (`src/supabase.ts`).

- **Supabase Auth.** With `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` in `frontend/.env.local`, Login is an email and password form on `@supabase/supabase-js` (2.117.2, pinned). Copy `frontend/.env.example` to `.env.local`, which git ignores. Vite reads `frontend/.env*`, not the root `.env`, and inlines the variables at build time, so rebuild or restart after changing them. Only the publishable key goes there: the secret key stays in the root `.env`. The API verifies the access token against the project's JWKS, so it needs `SUPABASE_URL`; the accounts come from `uv run python -m src.auth.seed_personas` (spec: `docs/specs/supabase-login-v1.md`).
- **Local personas.** Without both variables, Login is the local test issuer (`GET /api/v1/auth/personas`, `POST /api/v1/auth/test-session`), which the API exposes only when `APP_ENV` is `development` or `test`: unset, blank or any other value means production, where the issuer is off and the API refuses to start without `SUPABASE_URL`. Customer personas open the Chat; the agent button (customer id `AGENT-1`) opens the Console.

In both modes the app then reads `GET /api/v1/auth/me`, which returns the `app_role` and `customer_id` the API verified, and opens the Console for `agent` and the Chat for anyone else. With Supabase, a failed sign-in shows "Email or password is incorrect." for invalid credentials and Supabase's own message otherwise (rate limit, network), and a 403 from `/auth/me` (an account with no customer identity and no agent role) signs out and shows the API's message.

The session survives a page refresh and ends when the tab closes: supabase-js keeps its own in `sessionStorage` and every request takes a fresh access token from it; in local mode the token lives in memory and in `sessionStorage`. A 401 clears the session and sends you back to Login. Sign-out ends only the session in this browser (`signOut({ scope: 'local' })`): the demo accounts are shared, so a global sign-out would end other people's sessions.

## Build

```bash
cd frontend
npm run build
```

`tsc -b` type-checks first, then Vite writes the static bundle to `frontend/dist/` (index.html plus hashed assets). `npm run preview` serves that folder locally if you want to inspect it without the API. The sign-in mode is fixed in the bundle by the `VITE_SUPABASE_*` variables present when it is built (see Sign-in).

## How FastAPI serves the build

`src/api/app.py` mounts `frontend/dist` at `/` with `StaticFiles(html=True)` when that directory exists, so one process on port 8000 serves both the API under `/api/v1/...` and the UI at `/`. Build the frontend, then start the API and open http://localhost:8000. If `frontend/dist` is missing, the API runs without the UI.

Both `frontend/node_modules/` and `frontend/dist/` are git-ignored (root `.gitignore` plus `frontend/.gitignore`), so the build is a deployment step, not a committed artifact.

## Files

- `src/supabase.ts`: the Supabase client, or `null` when the build lacks `VITE_SUPABASE_URL` or `VITE_SUPABASE_PUBLISHABLE_KEY` (local mode). Its session lives in `sessionStorage`, and it reads no magic links or OAuth redirects (`detectSessionInUrl` is off).
- `src/api.ts`: TypeScript types for every response and a `fetch` wrapper that adds the bearer token (a fresh Supabase access token, or the stored local one), parses the API `detail` message and reports 401s. `api.me` reads the verified identity; `clearSession` forgets the session of this browser.
- `src/App.tsx`: state-based routing between Login, Chat and Console.
- `src/Login.tsx`: the email and password form in Supabase mode; the personas list and agent entry in local mode.
- `src/Chat.tsx`: language toggle (sent when the conversation starts), message list, candidate buttons that send the option number, lock confirmation buttons ("Sí" / "Sim" and "No" / "Não"), status line.
- `src/Console.tsx`: Cases (credit-candidate filter, Approve / Reject), Handoffs (open first, expandable packet, Resolve), Locks, Audit log (newest first, conversation filter). A 403 shows "This view requires the agent role".
- `src/styles.css`: neutral light theme, system font stack, 16px side gutters, phone width without horizontal scroll.
- `.env.example`: the two `VITE_SUPABASE_*` variables, empty; copy it to `.env.local` for the Supabase mode.
