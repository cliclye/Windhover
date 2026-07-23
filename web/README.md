# Windhover web

React/Vite interface for an OpenAI-compatible Windhover server.

```sh
npm install
npm run dev
```

The default endpoint is `http://127.0.0.1:8000/v1`. Start the API with
`./windhover app` or `./windhover serve`, then use **Probe server** to load its models.

Local validation:

```sh
npm test
npm run build
```

The test suite stays browser-light: API requests use a mocked `fetch`, while
runtime capability and storage behavior are covered through pure helpers. It
checks that `/health` is resolved next to (not below) the OpenAI `/v1` prefix,
supports both boolean and numeric `scheduler.active` responses, and sends the
Windhover-specific `cache_slot` field only when KV-slot support was advertised.

The endpoint and selected model are persisted locally. API keys are intentionally
memory-only; startup/persistence also clears any legacy localStorage API-key keys.
