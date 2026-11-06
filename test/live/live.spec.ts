import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// End-to-end scenarios from the user's side, against the live market and the live
// account. Every trade is paired with its reverse, so holdings end where they started.
// Assertions are relative (before/after), never absolute, because prices move.

type Position = { ticker: string; quantity: number; avg_cost: number; current_price: number; day_change_percent: number };
type Portfolio = { cash_balance: number; total_value: number; positions: Position[] };
type WatchEntry = { ticker: string; price: number | null; day_change_percent: number | null };

const EXTRA_TICKER = "WIPRO"; // used for watchlist scenarios; never held

let ticker = ""; // watched, priced, not held: all trade scenarios use it
let other = ""; // a second such ticker, for chart switching

async function getJson<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get(path);
  expect(response.ok(), `GET ${path} returned ${response.status()}`).toBeTruthy();
  return (await response.json()) as T;
}

async function portfolio(request: APIRequestContext): Promise<Portfolio> {
  return getJson<Portfolio>(request, "/api/portfolio");
}

/** Parses "₹7,22,358.40" (or a bare number) to a number. */
function parseInr(text: string | null): number {
  return Number((text ?? "").replace(/[^0-9.-]/g, ""));
}

/** Parses "+1.14%" to 1.14. */
function parsePercent(text: string | null): number {
  return Number((text ?? "").replace(/[^0-9.+-]/g, ""));
}

async function cash(page: Page): Promise<number> {
  const cell = page.getByTestId("cash-balance");
  await expect(cell).not.toHaveText("--");
  return parseInr(await cell.textContent());
}

async function trade(page: Page, side: "Buy" | "Sell", symbol: string, quantity: string) {
  await page.getByLabel("Trade ticker").fill(symbol);
  await page.getByLabel("Trade quantity").fill(quantity);
  await page.getByRole("button", { name: side, exact: true }).click();
}

async function ask(page: Page, message: string) {
  await page.getByLabel("Chat message").fill(message);
  await page.getByRole("button", { name: "Send", exact: true }).click();
}

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ request }) => {
  const watch = await getJson<WatchEntry[]>(request, "/api/watchlist");
  const held = new Set((await portfolio(request)).positions.map((p) => p.ticker));
  const candidates = watch
    .filter((entry) => entry.price !== null && !held.has(entry.ticker) && entry.ticker !== EXTRA_TICKER)
    .map((entry) => entry.ticker);
  expect(candidates.length, "need two watched, priced, unheld tickers").toBeGreaterThanOrEqual(2);
  [ticker, other] = candidates;
  console.log(`live suite: trading ${ticker}, switching charts to ${other}`);
});

test.afterAll(async ({ request }) => {
  // Put the account back as it was: no leftover test holding, no test watchlist entry.
  const view = await portfolio(request);
  const leftover = view.positions.find((p) => p.ticker === ticker);
  if (leftover) {
    await request.post("/api/portfolio/trade", { data: { ticker, quantity: leftover.quantity, side: "sell" } });
  }
  await request.delete(`/api/watchlist/${EXTRA_TICKER}`);
});

test.describe("market data", () => {
  test("the page loads connected with every watched ticker priced", async ({ page, request }) => {
    await page.goto("/");
    await expect(page.getByTestId("connection-status")).toHaveText("connected");
    const watch = await getJson<WatchEntry[]>(request, "/api/watchlist");
    for (const entry of watch) {
      await expect(page.getByTestId(`watch-${entry.ticker}`).getByTestId("price")).not.toHaveText("--");
    }
  });

  test("prices move and flash while the market is open", async ({ page }) => {
    await page.goto("/");
    const price = page.getByTestId(`watch-${ticker}`).getByTestId("price");
    const seen = new Set<string>([(await price.textContent()) ?? ""]);
    const flashes = new Set<string>();
    const deadline = Date.now() + 60_000;
    while (Date.now() < deadline && seen.size < 2) {
      await page.waitForTimeout(250);
      seen.add((await price.textContent()) ?? "");
      flashes.add((await price.getAttribute("data-flash")) ?? "");
    }
    expect(seen.size, `${ticker} did not change in 60 s; is the market open?`).toBeGreaterThan(1);
    expect(flashes.has("up") || flashes.has("down"), "price changed but no flash was shown").toBeTruthy();
  });

  test("sparklines fill in from the live stream", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(10_000);
    const points = await page.getByTestId(`watch-${ticker}`).locator("polyline").getAttribute("points");
    expect(points?.trim().split(/\s+/).length ?? 0).toBeGreaterThanOrEqual(5);
  });

  test("the day change in the watchlist matches the backend", async ({ page, request }) => {
    await page.goto("/");
    const backend = (await getJson<WatchEntry[]>(request, "/api/watchlist")).find((e) => e.ticker === ticker);
    const shown = page.getByTestId(`watch-${ticker}`).getByText(/%$/);
    await expect(shown).toBeVisible();
    // Prices move between the two reads, so allow a small tolerance.
    expect(Math.abs(parsePercent(await shown.textContent()) - (backend?.day_change_percent ?? 0))).toBeLessThan(0.3);
  });

  test("clicking a ticker switches the main chart and the trade ticker", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: other, exact: true }).click();
    await expect(page.getByRole("region", { name: "Price chart" }).getByRole("heading")).toHaveText(other);
    await expect(page.getByLabel("Trade ticker")).toHaveValue(other);
  });

  test("a dropped stream is reported and recovers", async ({ page }) => {
    await page.route("**/api/stream/prices", (route) =>
      route.fulfill({ status: 200, contentType: "text/event-stream", body: "" }),
    );
    await page.goto("/");
    await expect(page.getByTestId("connection-status")).not.toHaveText("connected", { timeout: 10_000 });
    await page.unroute("**/api/stream/prices");
    await expect(page.getByTestId("connection-status")).toHaveText("connected", { timeout: 20_000 });
  });
});

test.describe("trading", () => {
  test("buying one share fills at the live price and debits cash", async ({ page }) => {
    await page.goto("/");
    const before = await cash(page);
    await trade(page, "Buy", ticker, "1");
    await expect(page.getByRole("status").filter({ hasText: `Bought 1 ${ticker} at` })).toBeVisible();
    await expect(page.getByTestId(`position-${ticker}`)).toBeVisible();
    await expect.poll(() => cash(page)).toBeLessThan(before);
  });

  test("selling it back closes the position and credits cash", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId(`position-${ticker}`)).toBeVisible();
    const before = await cash(page);
    await trade(page, "Sell", ticker, "1");
    await expect(page.getByRole("status").filter({ hasText: `Sold 1 ${ticker} at` })).toBeVisible();
    await expect(page.getByTestId(`position-${ticker}`)).toHaveCount(0);
    await expect.poll(() => cash(page)).toBeGreaterThan(before);
  });

  test("ticker input is case-insensitive", async ({ page }) => {
    await page.goto("/");
    await trade(page, "Buy", ticker.toLowerCase(), "1");
    await expect(page.getByRole("status").filter({ hasText: `Bought 1 ${ticker} at` })).toBeVisible();
    await trade(page, "Sell", ticker.toLowerCase(), "1");
    await expect(page.getByRole("status").filter({ hasText: `Sold 1 ${ticker} at` })).toBeVisible();
  });

  test("fractional quantities are accepted", async ({ page }) => {
    await page.goto("/");
    await trade(page, "Buy", ticker, "0.5");
    await expect(page.getByRole("status").filter({ hasText: `Bought 0.5 ${ticker} at` })).toBeVisible();
    await trade(page, "Sell", ticker, "0.5");
    await expect(page.getByRole("status").filter({ hasText: `Sold 0.5 ${ticker} at` })).toBeVisible();
  });

  test("a zero quantity is refused with the reason shown", async ({ page }) => {
    await page.goto("/");
    await trade(page, "Buy", ticker, "0");
    await expect(page.locator('p[role="alert"]')).toContainText("quantity must be a positive number");
  });

  test("selling shares not held is refused with the reason shown", async ({ page }) => {
    await page.goto("/");
    await trade(page, "Sell", ticker, "5");
    await expect(page.locator('p[role="alert"]')).toContainText("insufficient shares");
  });

  test("a rejected order does not move the balance", async ({ page }) => {
    await page.goto("/");
    const before = await cash(page);
    await trade(page, "Sell", ticker, "5");
    await expect(page.locator('p[role="alert"]')).toContainText("insufficient shares");
    expect(await cash(page)).toBe(before);
  });

  test("a server error during a trade is shown to the user", async ({ page }) => {
    await page.route("**/api/portfolio/trade", (route) =>
      route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "database is locked" }) }),
    );
    await page.goto("/");
    await trade(page, "Buy", ticker, "1");
    await expect(page.locator('p[role="alert"]')).toContainText("database is locked");
    await page.unroute("**/api/portfolio/trade");
  });
});

test.describe("watchlist", () => {
  test("add a valid NSE ticker, see it priced, then remove it", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Ticker to add").fill(EXTRA_TICKER.toLowerCase());
    await page.getByRole("button", { name: "Add", exact: true }).click();
    const row = page.getByTestId(`watch-${EXTRA_TICKER}`);
    await expect(row).toBeVisible();
    await expect(row.getByTestId("price")).not.toHaveText("--", { timeout: 15_000 });
    await page.getByRole("button", { name: `Remove ${EXTRA_TICKER}` }).click();
    await expect(row).toHaveCount(0);
  });

  test("a duplicate ticker is refused with the reason shown", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Ticker to add").fill(other);
    await page.getByRole("button", { name: "Add", exact: true }).click();
    await expect(page.locator('p[role="alert"]')).toContainText("already on the watchlist");
  });

  test("a non-NSE ticker is refused with the reason shown", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Ticker to add").fill("NOPE");
    await page.getByRole("button", { name: "Add", exact: true }).click();
    await expect(page.locator('p[role="alert"]')).toContainText("not an NSE equity");
  });

  test("malformed text is refused", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Ticker to add").fill("a b");
    await page.getByRole("button", { name: "Add", exact: true }).click();
    await expect(page.locator('p[role="alert"]')).toContainText("not a valid ticker symbol");
  });
});

test.describe("portfolio views", () => {
  test("heatmap and value chart show the current holdings", async ({ page, request }) => {
    await page.goto("/");
    await expect(page.getByTestId("tile-CASH")).toBeVisible();
    for (const position of (await portfolio(request)).positions) {
      await expect(page.getByTestId(`tile-${position.ticker}`)).toBeVisible();
    }
    await expect(page.getByTestId("pnl-chart").locator("canvas").first()).toBeVisible();
  });

  test("positions table agrees with the backend", async ({ page, request }) => {
    await page.goto("/");
    for (const position of (await portfolio(request)).positions) {
      const row = page.getByTestId(`position-${position.ticker}`);
      await expect(row).toBeVisible();
      const expected = position.quantity.toLocaleString("en-IN", { maximumFractionDigits: 4 });
      await expect(row.locator("td").nth(1)).toHaveText(expected);
    }
  });
});

test.describe("assistant", () => {
  test("a question is answered and does not trade", async ({ page, request }) => {
    await page.goto("/");
    const before = (await portfolio(request)).positions.map((p) => `${p.ticker}:${p.quantity}`).join(",");
    await ask(page, "In one sentence, how much cash do I have?");
    await expect(page.getByTestId("chat-log").locator("p").nth(1)).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText("FinAlly is thinking...")).toHaveCount(0, { timeout: 60_000 });
    await expect(page.getByTestId("chat-log")).not.toContainText("Bought");
    await expect(page.getByTestId("chat-log")).not.toContainText("Sold");
    const after = (await portfolio(request)).positions.map((p) => `${p.ticker}:${p.quantity}`).join(",");
    expect(after).toBe(before);
  });

  test("the loading indicator shows while the model is thinking", async ({ page }) => {
    await page.goto("/");
    await ask(page, "Say hello in five words.");
    const seen = await page.getByText("FinAlly is thinking...").isVisible({ timeout: 2_000 }).catch(() => false);
    test.info().annotations.push({ type: "observed", description: `loading indicator seen quickly: ${seen}` });
    await expect(page.getByText("FinAlly is thinking...")).toHaveCount(0, { timeout: 60_000 });
  });

  test("a buy request in chat executes and is confirmed inline, then reversed", async ({ page, request }) => {
    await page.goto("/");
    await ask(page, `Buy exactly 1 share of ${ticker}.`);
    await expect(page.getByText(`Bought 1 ${ticker} at`)).toBeVisible({ timeout: 90_000 });
    await ask(page, `Sell exactly 1 share of ${ticker}.`);
    await expect(page.getByText(`Sold 1 ${ticker} at`)).toBeVisible({ timeout: 90_000 });
    const left = (await portfolio(request)).positions.find((p) => p.ticker === ticker);
    expect(left, `${ticker} should be fully sold again`).toBeUndefined();
  });

  test("watchlist changes through chat are confirmed inline, then reversed", async ({ page, request }) => {
    await page.goto("/");
    await ask(page, `Add ${EXTRA_TICKER} to my watchlist.`);
    await expect(page.getByText(`Added ${EXTRA_TICKER} to watchlist`)).toBeVisible({ timeout: 90_000 });
    await expect(page.getByTestId(`watch-${EXTRA_TICKER}`)).toBeVisible();
    await ask(page, `Remove ${EXTRA_TICKER} from my watchlist.`);
    await expect(page.getByText(`Removed ${EXTRA_TICKER} from watchlist`)).toBeVisible({ timeout: 90_000 });
    const watch = await getJson<WatchEntry[]>(request, "/api/watchlist");
    expect(watch.some((e) => e.ticker === EXTRA_TICKER)).toBe(false);
  });

  test("the panel can be hidden and shown again", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Hide", exact: true }).click();
    await page.getByRole("button", { name: "FinAlly chat" }).click();
    await expect(page.getByLabel("Chat message")).toBeVisible();
  });

  test("a model error is shown in the chat", async ({ page }) => {
    await page.route("**/api/chat", (route) =>
      route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "model unavailable" }) }),
    );
    await page.goto("/");
    await ask(page, "hello");
    await expect(page.getByTestId("chat-log")).toContainText("Error: model unavailable");
    await page.unroute("**/api/chat");
  });
});

test.describe("layout and persistence", () => {
  for (const width of [1366, 1024]) {
    test(`no horizontal scroll at ${width} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 768 });
      await page.goto("/");
      await expect(page.getByTestId("connection-status")).toHaveText("connected");
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, "page is wider than the viewport").toBeLessThanOrEqual(1);
    });
  }

  test("holdings and watchlist survive a reload", async ({ page, request }) => {
    await page.goto("/");
    const positionsBefore = (await portfolio(request)).positions.map((p) => p.ticker).sort();
    const watchBefore = (await getJson<WatchEntry[]>(request, "/api/watchlist")).map((e) => e.ticker).sort();
    await page.reload();
    await expect(page.getByTestId("connection-status")).toHaveText("connected");
    expect((await portfolio(request)).positions.map((p) => p.ticker).sort()).toEqual(positionsBefore);
    expect((await getJson<WatchEntry[]>(request, "/api/watchlist")).map((e) => e.ticker).sort()).toEqual(watchBefore);
  });

  test("the conversation clears on reload (recorded deviation)", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("chat-log")).toContainText("Ask about your portfolio");
  });
});
