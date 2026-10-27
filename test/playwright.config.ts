import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { defineConfig, devices } from '@playwright/test';

const BASE_URL = process.env.BASE_URL ?? 'http://localhost:8000';
const BACKEND_DIR = path.resolve(__dirname, '../backend');

/** A new SQLite file per run, so every local run starts from the seeded database. */
function freshDatabasePath(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'finally-e2e-'));
  return path.join(dir, 'finally.db');
}

export default defineConfig({
  testDir: './e2e',
  // All specs share one server and one database, so they run one at a time in file-name order.
  workers: 1,
  fullyParallel: false,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  // Local loop: start the backend ourselves. Container loop sets BASE_URL and the app runs elsewhere.
  webServer: process.env.BASE_URL
    ? undefined
    : {
        command: 'uv run uvicorn app.main:app --port 8000',
        cwd: BACKEND_DIR,
        url: `${BASE_URL}/api/health`,
        reuseExistingServer: false,
        timeout: 120_000,
        env: {
          DHAN_ACESS_TOKEN: '',
          MARKET_SEED: '42',
          LLM_MOCK: 'true',
          FINALLY_DB_PATH: freshDatabasePath(),
        },
      },
});
