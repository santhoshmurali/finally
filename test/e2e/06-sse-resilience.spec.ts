import { expect, test } from '@playwright/test';
import { watchlistRow } from './helpers';

test('price stream reconnects after a dropped connection and prices resume', async ({ page }) => {
  // The first stream request ends after a retry hint, which the browser sees as a dropped connection.
  // Later requests pass through to the real server. The 3 s retry keeps the reconnecting state visible.
  let streamRequests = 0;
  await page.route('**/api/stream/prices', async (route) => {
    streamRequests += 1;
    if (streamRequests === 1) {
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'retry: 3000\n\n' });
    } else {
      await route.continue();
    }
  });

  await page.goto('/');
  const status = page.getByTestId('connection-status');
  await expect(status).toHaveAttribute('data-state', 'reconnecting');
  await expect(status).toHaveAttribute('data-state', 'open');

  const tcsPrice = watchlistRow(page, 'TCS').getByTestId('watchlist-price');
  const priceAfterReconnect = await tcsPrice.getAttribute('data-price');
  await expect.poll(() => tcsPrice.getAttribute('data-price')).not.toBe(priceAfterReconnect);
});
