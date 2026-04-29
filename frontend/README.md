# Nova Frontend

This directory contains Nova's desktop-facing frontend shell built with:

- React
- Vite
- `@assistant-ui/react`

## Current Layout

- left sidebar for session switching and history replay
- collapsible thread-list sidebar with a floating toggle
- center area only keeps the thread viewport and bottom composer
- fixed bottom composer owned by `NovaAppShell`
- inline model selector beside the send button

## Development

Start the backend first:

```bash
python -m nova serve
```

Then start the frontend:

```bash
cd frontend
npm install
npm run dev
```

By default, Vite proxies `/api/*` and `/health` to `http://127.0.0.1:8765`.

Optional overrides:

- `NOVA_FRONTEND_PROXY_TARGET` for the Vite dev proxy target
- `VITE_NOVA_API_BASE_URL` for an explicit runtime API base URL

## Build

```bash
npm run build
```

The build output lands in `frontend/dist/` and is intended to be consumable by a future `pywebview` shell or backend static-file integration.
