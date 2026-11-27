# MRP frontend

The browser client is a separate Vite + TypeScript repository. It talks only to
the MRP HTTP API; no robot credentials are bundled into the browser build.

The operator UI is a strongly typed React app built with Material UI. Layout:

- `src/api/`: the only code that talks HTTP. `client.ts` wraps axios (errors become
  `ApiError` with the backend's message); one file per area holds typed endpoint
  functions; `queries.ts` has the TanStack Query hooks that poll live state.
- `src/router.tsx` and `src/routes/`: one URL per page (`/record`, `/train`, …), each
  page loaded on first visit. `src/workspace/` is the layout route: it shares live
  state, runs actions and asks before leaving unsaved cell edits.
- `src/pages/` and `src/components/`: prop-driven UI, tested without the router.
- `src/theme.ts`: colours by role (`shell.*`, `surface.*`, …); use those, not hex values.

```bash
corepack enable
yarn install
yarn dev
```

Start the FastAPI backend separately from `../backend`:

```bash
uv sync --locked
make run
```

Vite proxies API requests to `http://127.0.0.1:8088`; for a direct remote API
set `VITE_API_URL` to the backend URL and use the exact frontend origin in
`MRP_ALLOWED_ORIGINS`. Allow the API hostname with `--allow-host` when it is
not localhost. The camera preview uses the same API URL. The sidebar links to
the interactive FastAPI documentation.

`yarn check` runs Prettier, ESLint, TypeScript, and the production build. Husky
runs `lint-staged` before commits.

## Tests

Run `yarn test` for component tests and `yarn test:e2e` for Chromium browser
checks against controlled API responses. Install the browser once with
`yarn playwright install chromium` (Linux may also need Playwright's system
dependencies: `yarn playwright install-deps chromium`). The CI pipeline runs
both suites and saves browser traces and JUnit results when a test fails. Set
`MRP_REAL_E2E=1` in GitLab CI and allow the frontend project’s job token to
read the backend repository to also run the real demo-backend browser job. The
job checks out the backend default branch.

To test the frontend, Vite proxy, and actual backend together, check out the
backend as `../backend`, install its Python dependencies, and run
`yarn test:e2e:real`. This starts a demo backend on port 18088 and Vite on port
4173, using a temporary data directory. Both ports must be free. The demo
runtime does not operate hardware or produce real datasets. The backend's own
unit and HTTP tests can be run with `make test` in `../backend`; its CI runs
them separately. Real robot, camera, and export integrations require the
separate mock-ROS integration environment described in the backend repository.
