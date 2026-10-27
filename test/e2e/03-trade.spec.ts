import { expect, test } from '@playwright/test';
import { positionRow, readCash, submitTrade } from './helpers';

test('buy: cash decreases by quantity times price and a position appears', async ({ page }) => {
  await page.goto('/');
  const cashBefore = await readCash(page);

  const { trade } = await submitTrade(page, 'TCS', 5, 'buy');

  await expect(positionRow(page, 'TCS').getByTestId('position-quantity')).toHaveText(/^5(\.0+)?$/);
  await expect.poll(() => readCash(page)).toBeCloseTo(cashBefore - 5 * trade.price, 1);
});

test('sell: cash increases and the position shrinks, then disappears', async ({ page }) => {
  await page.goto('/');
  const cashStart = await readCash(page);
  const bought = await submitTrade(page, 'INFY', 2, 'buy');
  const cashAfterBuy = cashStart - 2 * bought.trade.price;
  await expect.poll(() => readCash(page)).toBeCloseTo(cashAfterBuy, 1);

  const soldOne = await submitTrade(page, 'INFY', 1, 'sell');
  await expect(positionRow(page, 'INFY').getByTestId('position-quantity')).toHaveText(/^1(\.0+)?$/);
  await expect.poll(() => readCash(page)).toBeCloseTo(cashAfterBuy + soldOne.trade.price, 1);

  await submitTrade(page, 'INFY', 1, 'sell');
  await expect(positionRow(page, 'INFY')).toHaveCount(0);
});
