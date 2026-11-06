// Functional scenarios against a running FinAlly backend (live or simulator).
//
//   BASE_URL=http://localhost:8000 node test/functional/scenarios.mjs
//
// These trade real (virtual) money on whatever prices the backend is streaming.
// They use one ticker that is watched but not held, and sell back everything they
// bought, so the portfolio ends in the state it started in (cash changes only by
// the net effect of the buy/sell round trips, which is zero for the same quantity).

import assert from "node:assert/strict";

const BASE = process.env.BASE_URL ?? "http://localhost:8000";
const results = [];

async function api(method, path, body) {
  const response = await fetch(`${BASE}${path}`, {
    method,
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const json = response.status === 204 ? null : await response.json().catch(() => null);
  return { status: response.status, body: json };
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const portfolio = async () => (await api("GET", "/api/portfolio")).body;

// A ticker that was just added has no price until its first tick arrives, and a
// trade on it is rejected with "not priced yet" until then. Retry that case only,
// and report how many retries it took so the delay stays visible.
async function tradeWhenPriced(body) {
  let retries = 0;
  for (;;) {
    const response = await api("POST", "/api/portfolio/trade", body);
    const notPriced = response.status === 400 && /not priced yet/.test(response.body?.detail ?? "");
    if (!notPriced || retries >= 20) {
      if (retries > 0) console.log(`      (${body.ticker} ${body.side} waited for its first price: ${retries} retries)`);
      return response;
    }
    retries += 1;
    await sleep(500);
  }
}

async function waitForWatchPrice(ticker) {
  for (let attempt = 0; attempt < 20; attempt++) {
    const entry = (await api("GET", "/api/watchlist")).body.find((e) => e.ticker === ticker);
    if (entry?.price != null) return entry;
    await sleep(500);
  }
  return null;
}
const holding = (view, ticker) => view.positions.find((p) => p.ticker === ticker);
const near = (actual, expected, tolerance = 0.01) =>
  assert.ok(
    Math.abs(actual - expected) <= tolerance,
    `expected ${expected} +/- ${tolerance}, got ${actual}`,
  );

async function scenario(name, run) {
  try {
    await run();
    results.push({ name, ok: true });
    console.log(`PASS  ${name}`);
  } catch (error) {
    results.push({ name, ok: false, error: error.message });
    console.log(`FAIL  ${name}\n      ${error.message}`);
  }
}

// Pick a watched, priced ticker that is not held, so the scenarios start clean.
async function pickTicker() {
  const watch = (await api("GET", "/api/watchlist")).body;
  const view = await portfolio();
  const candidate = watch.find(
    (entry) => entry.price !== null && !holding(view, entry.ticker),
  );
  assert.ok(candidate, "no watched, priced, unheld ticker available");
  return candidate.ticker;
}

const health = (await api("GET", "/api/health")).body;
console.log(`Backend ${BASE}: market source ${health.market_source}, healthy=${health.market_source_healthy}`);
assert.equal(health.market_source_healthy, true, "market source is not healthy");

const TICKER = await pickTicker();
console.log(`Using ${TICKER} for the scenarios\n`);

const startingCash = (await portfolio()).cash_balance;

await scenario("buy opens a position at the trade price and debits cash", async () => {
  const before = await portfolio();
  const trade = await api("POST", "/api/portfolio/trade", { ticker: TICKER, quantity: 2, side: "buy" });
  assert.equal(trade.status, 200);
  const after = await portfolio();
  const position = holding(after, TICKER);
  assert.equal(position.quantity, 2);
  near(position.avg_cost, trade.body.price, 0.005);
  near(before.cash_balance - after.cash_balance, 2 * trade.body.price, 0.01);
});

await scenario("second buy averages the cost of the two lots", async () => {
  const first = holding(await portfolio(), TICKER);
  const trade = await api("POST", "/api/portfolio/trade", { ticker: TICKER, quantity: 1, side: "buy" });
  assert.equal(trade.status, 200);
  const position = holding(await portfolio(), TICKER);
  assert.equal(position.quantity, 3);
  const expected = (2 * first.avg_cost + trade.body.price) / 3;
  near(position.avg_cost, expected, 0.01);
});

await scenario("partial sell reduces quantity and keeps the average cost", async () => {
  const before = await portfolio();
  const held = holding(before, TICKER);
  const trade = await api("POST", "/api/portfolio/trade", { ticker: TICKER, quantity: 1, side: "sell" });
  assert.equal(trade.status, 200);
  const after = await portfolio();
  const position = holding(after, TICKER);
  assert.equal(position.quantity, 2);
  near(position.avg_cost, held.avg_cost, 0.005);
  near(after.cash_balance - before.cash_balance, trade.body.price, 0.01);
});

await scenario("fractional quantities are bought and sold exactly", async () => {
  const buy = await api("POST", "/api/portfolio/trade", { ticker: TICKER, quantity: 0.5, side: "buy" });
  assert.equal(buy.status, 200);
  assert.equal(holding(await portfolio(), TICKER).quantity, 2.5);
  const sell = await api("POST", "/api/portfolio/trade", { ticker: TICKER, quantity: 0.5, side: "sell" });
  assert.equal(sell.status, 200);
  assert.equal(holding(await portfolio(), TICKER).quantity, 2);
});

await scenario("selling more than held is rejected and changes nothing", async () => {
  const before = await portfolio();
  const trade = await api("POST", "/api/portfolio/trade", { ticker: TICKER, quantity: 999, side: "sell" });
  assert.equal(trade.status, 400);
  assert.match(trade.body.detail, /insufficient shares/);
  const after = await portfolio();
  assert.equal(holding(after, TICKER).quantity, holding(before, TICKER).quantity);
  assert.equal(after.cash_balance, before.cash_balance);
});

await scenario("buying more than the cash balance is rejected and changes nothing", async () => {
  const before = await portfolio();
  const trade = await api("POST", "/api/portfolio/trade", { ticker: TICKER, quantity: 1e9, side: "buy" });
  assert.equal(trade.status, 400);
  assert.match(trade.body.detail, /insufficient cash/);
  assert.equal((await portfolio()).cash_balance, before.cash_balance);
});

await scenario("zero, negative and unknown-side orders are rejected", async () => {
  for (const body of [
    { ticker: TICKER, quantity: 0, side: "buy" },
    { ticker: TICKER, quantity: -1, side: "buy" },
    { ticker: TICKER, quantity: 1, side: "short" },
  ]) {
    const response = await api("POST", "/api/portfolio/trade", body);
    assert.equal(response.status, 400, `expected 400 for ${JSON.stringify(body)}`);
  }
});

await scenario("a successful trade adds a portfolio snapshot", async () => {
  const before = (await api("GET", "/api/portfolio/history")).body.length;
  const trade = await api("POST", "/api/portfolio/trade", { ticker: TICKER, quantity: 1, side: "buy" });
  assert.equal(trade.status, 200);
  const after = (await api("GET", "/api/portfolio/history")).body.length;
  assert.ok(after > before, `snapshots went from ${before} to ${after}`);
  await api("POST", "/api/portfolio/trade", { ticker: TICKER, quantity: 1, side: "sell" });
});

await scenario("full sell removes the position and the ticker stays priced while watched", async () => {
  const held = holding(await portfolio(), TICKER);
  const trade = await api("POST", "/api/portfolio/trade", { ticker: TICKER, quantity: held.quantity, side: "sell" });
  assert.equal(trade.status, 200);
  assert.equal(holding(await portfolio(), TICKER), undefined);
  const watch = (await api("GET", "/api/watchlist")).body.find((entry) => entry.ticker === TICKER);
  assert.ok(watch, `${TICKER} should still be on the watchlist`);
  assert.notEqual(watch.price, null, `${TICKER} should still have a live price`);
});

await scenario("buying an unwatched NSE ticker prices it, and selling it all leaves the book clean", async () => {
  const symbol = "WIPRO";
  const watched = (await api("GET", "/api/watchlist")).body.some((entry) => entry.ticker === symbol);
  assert.equal(watched, false, `${symbol} must not be on the watchlist for this scenario`);
  let bought = false;
  try {
    const buy = await tradeWhenPriced({ ticker: symbol, quantity: 1, side: "buy" });
    assert.equal(buy.status, 200, `buy rejected: ${buy.body?.detail}`);
    bought = true;
    const position = holding(await portfolio(), symbol);
    assert.notEqual(position.current_price, null);
  } finally {
    if (bought) {
      const sell = await api("POST", "/api/portfolio/trade", { ticker: symbol, quantity: 1, side: "sell" });
      assert.equal(sell.status, 200, "clean-up sell failed");
    }
  }
  assert.equal(holding(await portfolio(), symbol), undefined);
});

await scenario("watchlist: duplicate, malformed, unsupported and unknown removals are rejected", async () => {
  assert.equal((await api("POST", "/api/watchlist", { ticker: TICKER })).status, 409);
  assert.equal((await api("POST", "/api/watchlist", { ticker: "a b" })).status, 400);
  assert.equal((await api("POST", "/api/watchlist", { ticker: "NOTNSE" })).status, 400);
  assert.equal((await api("DELETE", "/api/watchlist/ZZZNOTWATCHED")).status, 404);
});

await scenario("watchlist: add then remove an NSE ticker round-trips", async () => {
  const symbol = "WIPRO";
  try {
    const add = await api("POST", "/api/watchlist", { ticker: symbol });
    assert.equal(add.status, 201);
    const priced = await waitForWatchPrice(symbol);
    assert.ok(priced, "added ticker should receive a price within 10 s");
  } finally {
    await api("DELETE", `/api/watchlist/${symbol}`);
  }
  const tickers = (await api("GET", "/api/watchlist")).body.map((entry) => entry.ticker);
  assert.equal(tickers.includes(symbol), false);
});

await scenario("chat: a buy request executes and the trade is reported", async () => {
  const response = await api("POST", "/api/chat", { message: `Please buy 1 share of ${TICKER}.` });
  assert.equal(response.status, 200);
  assert.ok(response.body.trades?.some((t) => t.ticker === TICKER && t.side === "buy"),
    `no buy of ${TICKER} in reply: ${JSON.stringify(response.body)}`);
  // Undo the chat trade so the scenario leaves nothing behind.
  await api("POST", "/api/portfolio/trade", { ticker: TICKER, quantity: 1, side: "sell" });
});

// Final clean-up: if anything was left held, sell it back.
const leftover = holding(await portfolio(), TICKER);
if (leftover) {
  await api("POST", "/api/portfolio/trade", { ticker: TICKER, quantity: leftover.quantity, side: "sell" });
}

const passed = results.filter((r) => r.ok).length;
console.log(`\n${passed}/${results.length} scenarios passed (starting cash ${startingCash.toFixed(2)}, ending cash ${(await portfolio()).cash_balance.toFixed(2)})`);
process.exitCode = passed === results.length ? 0 : 1;
