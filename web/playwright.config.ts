import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 30_000,
  use: { baseURL: "http://127.0.0.1:4173", viewport: { width: 1200, height: 800 } },
  webServer: { command: "npm run build && npm run preview", url: "http://127.0.0.1:4173", reuseExistingServer: true, timeout: 120_000 },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
