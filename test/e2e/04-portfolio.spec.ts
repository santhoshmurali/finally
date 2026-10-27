import { expect, test } from '@playwright/test';
import { submitTrade } from './helpers';

test('heatmap shows a tile per position and cash, and the P&L chart has points', async ({ page }) => {
  await page.goto('/');
  await submitTrade(page, 'ITC', 3, 'buy');

  await expect(page.locator('[data-testid="heatmap-tile"][data-ticker="ITC"]')).toBeVisible();
  await expect(page.locator('[data-testid="heatmap-tile"][data-ticker="CASH"]')).toBeVisible();
  await expect(page.locator('[data-testid="heatmap-tile"][data-ticker="ITC"]')).toHaveAttribute(
    'data-pnl',
    /^(gain|loss|flat)$/,
  );

  await expect
    .poll(async () => Number(await page.getByTestId('pnl-chart').getAttribute('data-point-count')))
    .toBeGreaterThan(0);
});
