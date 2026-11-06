import { expect, test, type Page } from "@playwright/test";

const DEFAULT_TICKERS = [
  "RELIANCE",
  "TCS",
  "INFY",
  "HDFCBANK",
  "ICICIBANK",
  "SBIN",
  "BHARTIARTL",
  "ITC",
  "LT",
  "HINDUNILVR",
];

/** Reads an INR amount such as "₹9,98,803.80" as a number. */
function parseInr(text: string | null): number {
  return Number((text ?? "").replace(/[^0-9.-]/g, ""));
}

/** Waits for the header to show a real balance (it starts as "--") and returns it. */
async function cashBalance(page: Page): Promise<number> {
  const cash = page.getByTestId("cash-balance");
  await expect(cash).not.toHaveText("--");
  return parseInr(await cash.textContent());
}

async function sendChat(page: Page, message: string) {
  await page.getByLabel("Chat message").fill(message);
  await page.getByRole("button", { name: "Send" }).click();
}

async function trade(page: Page, side: "Buy" | "Sell", ticker: string, quantity: number) {
  await page.getByLabel("Trade ticker").fill(ticker);
  await page.getByLabel("Trade quantity").fill(String(quantity));
  await page.getByRole("button", { name: side, exact: true }).click();
}

// Scenarios are ordered: each builds on the state the previous one left behind.
test.describe.configure({ mode: "serial" });

test("fresh start shows the default watchlist, starting cash and live prices", async ({ page }) => {
  await page.goto("/");

  for (const ticker of DEFAULT_TICKERS) {
    await expect(page.getByTestId(`watch-${ticker}`)).toBeVisible();
  }
  await expect(page.getByTestId("cash-balance")).toHaveText("₹10,00,000.00");
  await expect(page.getByTestId("connection-status")).toHaveText("connected");

  const tcsPrice = page.getByTestId("watch-TCS").getByTestId("price");
  await expect(tcsPrice).not.toHaveText("--");
  const first = await tcsPrice.textContent();
  await expect
    .poll(async () => {
      const current = await tcsPrice.textContent();
      return current !== first;
    }, { timeout: 10_000 })
    .toBe(true);
});

test("a ticker can be added to and removed from the watchlist", async ({ page }) => {
  await page.goto("/");

  await page.getByLabel("Ticker to add").fill("wipro");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByTestId("watch-WIPRO")).toBeVisible();

  await page.getByRole("button", { name: "Remove WIPRO" }).click();
  await expect(page.getByTestId("watch-WIPRO")).toHaveCount(0);
});

test("buying shares debits cash and opens a position", async ({ page }) => {
  await page.goto("/");
  const before = await cashBalance(page);

  await trade(page, "Buy", "TCS", 2);

  await expect(page.getByRole("status").filter({ hasText: "Bought 2 TCS" })).toBeVisible();
  await expect(page.getByTestId("position-TCS")).toBeVisible();
  await expect.poll(() => cashBalance(page)).toBeLessThan(before);
});

test("selling shares credits cash and closes the position", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("position-TCS")).toBeVisible();
  const before = await cashBalance(page);

  await trade(page, "Sell", "TCS", 2);

  await expect(page.getByRole("status").filter({ hasText: "Sold 2 TCS" })).toBeVisible();
  await expect(page.getByTestId("position-TCS")).toHaveCount(0);
  await expect.poll(() => cashBalance(page)).toBeGreaterThan(before);
});

test("heatmap and P&L chart render from the portfolio", async ({ page }) => {
  await page.goto("/");
  await trade(page, "Buy", "INFY", 1);
  await expect(page.getByTestId("position-INFY")).toBeVisible();

  await expect(page.getByTestId("tile-CASH")).toBeVisible();
  await expect(page.getByTestId("tile-INFY")).toHaveAttribute("data-pnl", /^-?[0-9.]+$/);
  await expect(page.getByTestId("pnl-chart").locator("canvas").first()).toBeVisible();

  const history = await page.request.get("/api/portfolio/history");
  expect(history.ok()).toBe(true);
  expect((await history.json()).length).toBeGreaterThan(1);
});

test("the mocked assistant replies and its trade appears inline", async ({ page }) => {
  await page.goto("/");

  await sendChat(page, "Buy one share of TCS");

  await expect(page.getByText("Mock FinAlly: I bought 1 share of TCS for you.")).toBeVisible();
  await expect(page.getByText(/Bought 1 TCS at/)).toBeVisible();
});

test("the price stream reconnects after it is interrupted", async ({ page }) => {
  // The stream answers with an empty body, so EventSource drops the connection and retries.
  await page.route("**/api/stream/prices", (route) =>
    route.fulfill({ status: 200, contentType: "text/event-stream", body: "" }),
  );
  await page.goto("/");
  await expect(page.getByTestId("connection-status")).not.toHaveText("connected", {
    timeout: 10_000,
  });

  await page.unroute("**/api/stream/prices");
  await expect(page.getByTestId("connection-status")).toHaveText("connected", { timeout: 15_000 });
});
