# dSentry UI

The dSentry dashboard is a React 19 and TypeScript application built with Vite. It talks to the FastAPI service through the generated client in `src/client`.

## Development

```bash
pnpm install --frozen-lockfile
cp .env.example .env
pnpm dev
```

The Vite development server proxies `/api` to the backend. Set `VITE_PROXY_TARGET` when the backend is not running at the default target in `vite.config.ts`.

## Commands

| Command | Purpose |
|---|---|
| `pnpm dev` | Start the development server |
| `pnpm build` | Type-check and build the production bundle |
| `pnpm typecheck` | Run TypeScript without emitting files |
| `pnpm lint` | Run Oxlint |
| `pnpm check` | Run typecheck, lint, and build |
| `pnpm codegen` | Regenerate `src/client` from `openapi.json` |

Vitest covers formatting and metric-mapping helpers (`src/lib/*.test.ts`). Run with `pnpm test`.

## Structure

- `src/pages` contains route-level screens.
- `src/components` contains reusable page and UI components.
- `src/context` contains providers and their separate hooks.
- `src/lib` contains API, formatting, and metric helpers.
- `src/client` is generated code. Update `openapi.json` and run `pnpm codegen`; do not hand-edit generated files.

Environment variables and proxy behavior are documented in `.env.example`.
