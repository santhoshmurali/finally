import { expect, test, type APIResponse } from '@playwright/test';
import { positionRow } from './helpers';

interface PortfolioBody {
  positions: { ticker: string; quantity: number }[];
}

async function heldQuantity(response: APIResponse, ticker: string): Promise<number> {
  const body = (await response.json()) as PortfolioBody;
  return body.positions.find((position) => position.ticker === ticker)?.quantity ?? 0;
}

test('mocked AI chat: reply appears, trade shows inline and updates the portfolio', async ({ page }) => {
  await page.goto('/');
  const quantityBefore = await heldQuantity(await page.request.get('/api/portfolio'), 'TCS');

  await page.getByTestId('chat-input').fill('Buy one TCS');
  await page.getByTestId('chat-send').click();

  await expect(page.locator('[data-testid="chat-message"][data-role="user"]')).toContainText('Buy one TCS');
  await expect(page.locator('[data-testid="chat-message"][data-role="assistant"]')).toContainText(
    'Bought 1 TCS (mock reply).',
  );
  await expect(page.getByTestId('chat-trade')).toContainText('TCS');

  await expect
    .poll(async () => heldQuantity(await page.request.get('/api/portfolio'), 'TCS'))
    .toBe(quantityBefore + 1);
  await expect(positionRow(page, 'TCS')).toBeVisible();
});
