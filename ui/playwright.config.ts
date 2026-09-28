import { defineConfig } from "@playwright/test";

// Browser end-to-end tests against a real server (see e2e/start-server.sh). Build the UI first: npm run build
const PORT = Number(process.env.VANGUARD_E2E_PORT ?? 8765);
export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  reporter: [["list"], ["html", { open: "never", outputFolder: "e2e-report" }]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } : {},
  },
  webServer: { command: "bash e2e/start-server.sh", url: `http://127.0.0.1:${PORT}/health`, reuseExistingServer: false, timeout: 60_000 },
});
