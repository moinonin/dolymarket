# COMMAND_RUNWAY: dexbuilder-live-stream

# Feature
**Name:** dexbuilder-live-stream
**Purpose:** Stream the upstream DexBuilder public market data into the browser over the Dolymarket websocket envelope instead of polling every 15 seconds.
**Reference Specification:** `.githeri/specs/dexbuilder-live-stream.spec.yaml`
**Expected Deliverables:**
- `app/ws/dexbuilder_stream.py` — upstream subscribe envelope, translation, session.
- `app/api/v4/ws_live.py` — `/api/v4/prediction/live/ws` route.
- `frontend/src/api/reconnectingSocket.ts` — `liveSocketUrl()` helper.
- `frontend/src/pages/LiveMarketDetailPage.tsx` — live depth/bbo/trades with the REST fallback kept.
- `requirements.txt`, `.env.example` — dependency and configuration.
- `tests/test_dexbuilder_stream.py` — hermetic tests against a local fake broker.

**Dependencies:**
- `fastapi`
- `websockets`
- `pytest`, `pytest-asyncio`

**Assumptions:**
- The upstream broker speaks the documented envelope and needs no auth for public channels.
- The broker currently answers HTTP 503, so the route must degrade instead of blocking.

---

# Global Success Criteria
- The browser speaks only the Dolymarket envelope; the upstream broker stays server-side.
- Depth, bbo and trades arrive as live websocket messages with Decimal-accurate values.
- An unreachable upstream produces a clean error frame and leaves REST polling working.
- `pytest`, `ruff`, `githeri verify` and `npm run build` all pass.

---

# Phase 1 — Backend
1. `app/ws/dexbuilder_stream.py`: `build_subscribe_request()`, `translate_message()`, `DexBuilderStreamSession` (connect, subscribe, read loop, close).
2. `app/api/v4/ws_live.py`: the `/api/v4/prediction/live/ws` route that accepts the local subscribe envelope, forwards to the upstream and returns translated frames.
3. Register the router in `app/main.py`.

# Phase 2 — Frontend
1. `liveSocketUrl()` resolving `VITE_WS_URL` with a same-origin fallback.
2. `LiveMarketDetailPage`: subscribe to `pred.depth` / `pred.bbo` / `pred.trades`, update the book and the tape, keep the REST polling fallback and show the stream state.
3. `SocketSubscription` gains `condition_id` / `market_id`.

# Phase 3 — Verification
1. `tests/test_dexbuilder_stream.py`: envelope builder, translation, fake-broker round trip, unreachable-upstream degradation.
2. `pytest -q`, `ruff check app tests --select F821,F811,E9`, `githeri verify`, `npm run build`, `mkdocs build --strict`.
3. Update `docs/live-data.md`, `docs/dexbuilder-todo.md` and `.env.example`.
