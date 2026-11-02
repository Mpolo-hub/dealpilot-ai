# DealPilot AI frontend (first release)

Read-only web interface over the spec 002 API: Dashboard, Sales analysis, Products and Data
(`specs/007-frontend.md`, Implemented for RC1). Local use only: every server listens on `127.0.0.1`;
never expose the app or the API on a network (spec 007 D1).

## Run locally
1. Start the API from `backend/` (it needs the generated dataset in `data/raw`):
   ```powershell
   .venv\Scripts\python.exe -m uvicorn dealpilot.api.main:app --host 127.0.0.1 --port 8000
   ```
2. From `frontend/`:
   ```powershell
   npm run dev       # http://127.0.0.1:5173, proxies /v1 and /health to the API
   npm run build     # type check, then the static build in dist/
   npm run preview   # http://127.0.0.1:4173, the build with the same proxy
   ```
Pages and API share one origin through the Vite proxy, so the API needs no CORS, and the
proxy adds none (`cors: false`, spec 007 D9).

## Checks
```powershell
npm run typecheck   # tsc --noEmit (strict)
npm run lint        # ESLint (recommended, typescript-eslint, rules of hooks)
npm test            # Vitest: unit and page tests against a fake spec 002 API
```
End-to-end and screenshot checks with Playwright (spec 007 D13) need browser binaries,
which are not installed yet.

## Dependencies
Exact versions in `package.json` and `package-lock.json` (spec 007 section 12.9). Install
with `npm ci --ignore-scripts`; never change a version without approval.

## License notices
The Inter typeface (`@fontsource/inter`) is under the SIL Open Font License 1.1; the build
copies its license to `dist/licenses/inter-OFL-1.1.txt`. The JavaScript in the build comes
from MIT-licensed packages (React, React DOM, scheduler, React Router and its two helpers).
