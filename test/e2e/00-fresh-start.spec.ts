import { expect, test } from '@playwright/test';
import { DEFAULT_TICKERS, watchlistRow } from './helpers';

test.beforeEach(async ({ page }) => {
  await page.goto('/');
});

test('shows the ten default watchlist tickers', async ({ page }) => {
  const rows = page.getByTestId('watchlist-row');
  await expect(rows).toHaveCount(DEFAULT_TICKERS.length);
  const tickers = await rows.evaluateAll((els) => els.map((el) => el.getAttribute('data-ticker')));
  expect(tickers.sort()).toEqual([...DEFAULT_TICKERS].sort());
});

test('shows ₹10,00,000 of cash', async ({ page }) => {
  await expect(page.getByTestId('header-cash')).toContainText('10,00,000');
});

test('connection indicator is green', async ({ page }) => {
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-state', 'open');
});

test('streams live prices', async ({ page }) => {
  const tcsPrice = watchlistRow(page, 'TCS').getByTestId('watchlist-price');
  const firstPrice = await tcsPrice.getAttribute('data-price');
  await expect.poll(() => tcsPrice.getAttribute('data-price')).not.toBe(firstPrice);
});
