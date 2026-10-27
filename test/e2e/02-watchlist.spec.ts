import { expect, test } from '@playwright/test';
import { watchlistRow } from './helpers';

test('adds a ticker, keeps it after reload, then removes it', async ({ page }) => {
  await page.goto('/');

  await page.getByTestId('watchlist-add-input').fill('WIPRO');
  await page.getByTestId('watchlist-add-button').click();
  await expect(watchlistRow(page, 'WIPRO')).toBeVisible();

  await page.reload();
  await expect(watchlistRow(page, 'WIPRO')).toBeVisible();

  await watchlistRow(page, 'WIPRO').getByTestId('watchlist-remove').click();
  await expect(watchlistRow(page, 'WIPRO')).toHaveCount(0);
});
