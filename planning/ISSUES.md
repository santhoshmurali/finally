# FinAlly - Issues

Issue log for the E2E loop. Protocol: [TEAM_CONTRACT.md](TEAM_CONTRACT.md) section 9.

Status flow: `open` -> `fixed` (owner) -> `verified` (tester re-ran it and it passed) -> `closed`.

| ID | Owner | Status | Summary |
|---|---|---|---|
| E2E-001 | frontend-engineer | closed | UI hooks and attributes did not match TEAM_CONTRACT section 6 (connection-status, watchlist-price, watchlist add hooks, position-quantity, heatmap-tile data-pnl) |

## Issue details

### E2E-001: UI hooks and attributes do not match TEAM_CONTRACT section 6
- Owner: frontend-engineer
- Covers the earlier per-item IDs E2E-002 to E2E-005 (watchlist-price, add hooks, position-quantity, heatmap data-pnl). Those were merged into this single owner issue at the lead's request, and each is closed with it.
- Status: closed (2026-10-27). Fixed per owner note. Verified on the local loop (10 of 10 on the rebuilt `frontend/out`) and on the container loop (fresh build, 10 of 10 passed, playwright exit 0, log `container2.log`, 308 lines, ended 12:09:20).
- Repro: `cd test && npx playwright test` (the first run failed 7 tests on the old build; the earlier container run listed the same failures).
- Expected: the hook names and attributes in TEAM_CONTRACT section 6 (`connection-status` with `data-state`, `watchlist-price` with `data-price`, `watchlist-add-input` and `watchlist-add-button`, `position-quantity`, `heatmap-tile` with `data-pnl`, `pnl-chart` with `data-point-count`).
- Actual (old build): `connection-status` had `data-status` only; `watchlist-price` had no `data-price`; the add hooks were `watchlist-input` and `watchlist-add`; `position-quantity` was missing; `heatmap-tile` had no `data-pnl`.
- Failing specs (old build): `00-fresh-start.spec.ts` (connection indicator, streams live prices), `02-watchlist.spec.ts`, `03-trade.spec.ts` (buy and sell), `04-portfolio.spec.ts`, `06-sse-resilience.spec.ts`.
- Fix note (frontend-engineer), per item:
  - connection-status: first build set `data-status` only. `Header.tsx` now sets `data-state={status}`.
  - watchlist-price: had no `data-price`. `WatchlistRow.tsx` sets the numeric `data-price` (omitted while unknown).
  - add controls: were `watchlist-input` and `watchlist-add`. `Watchlist.tsx` renames them to `watchlist-add-input` and `watchlist-add-button`.
  - position-quantity: missing. `PositionsTable.tsx` adds it to the quantity cell.
  - heatmap-tile: no P&L attribute. `heatmap.ts` classifies tiles (`pnlDirection`) and `Heatmap.tsx` sets `data-pnl` to gain, loss or flat; the cash tile is flat.
  - frontend unit tests: 13 files, 49 tests pass; `npm run build` exits 0 (reported by frontend-engineer).

## Not app issues

- The SSE reconnect spec first failed because its `page.route` was installed after the page had already opened its stream, so the existing stream never errored. The spec now ends the first stream request with a `retry: 3000` body. This was a test bug, fixed in `test/e2e/06-sse-resilience.spec.ts`.
