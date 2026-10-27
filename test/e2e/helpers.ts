import { expect, type Locator, type Page } from '@playwright/test';

export const DEFAULT_TICKERS = [
  'RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK',
  'SBIN', 'BHARTIARTL', 'ITC', 'LT', 'HINDUNILVR',
];

export type Side = 'buy' | 'sell';

export interface TradeResult {
  trade: { ticker: string; side: Side; quantity: number; price: number };
}

/** Parses an en-IN money string such as "₹10,00,000.00" into a number. */
export function inrToNumber(text: string): number {
  return Number(text.replace(/[^\d.-]/g, ''));
}

/** Waits for the header cash to show a value, then returns it. */
export async function readCash(page: Page): Promise<number> {
  const cash = page.getByTestId('header-cash');
  await expect(cash).toHaveText(/₹\d/);
  return inrToNumber(await cash.innerText());
}

export function watchlistRow(page: Page, ticker: string): Locator {
  return page.locator(`[data-testid="watchlist-row"][data-ticker="${ticker}"]`);
}

export function positionRow(page: Page, ticker: string): Locator {
  return page.locator(`[data-testid="position-row"][data-ticker="${ticker}"]`);
}

/** Fills the trade bar, clicks buy or sell, and returns the trade response body. */
export async function submitTrade(
  page: Page,
  ticker: string,
  quantity: number,
  side: Side,
): Promise<TradeResult> {
  await page.getByTestId('trade-ticker').fill(ticker);
  await page.getByTestId('trade-quantity').fill(String(quantity));
  const tradeResponse = page.waitForResponse(
    (response) => response.url().endsWith('/api/portfolio/trade') && response.request().method() === 'POST',
  );
  await page.getByTestId(side === 'buy' ? 'trade-buy' : 'trade-sell').click();
  const response = await tradeResponse;
  expect(response.status(), 'trade request status').toBe(200);
  return (await response.json()) as TradeResult;
}
