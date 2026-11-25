import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60000,
  workers: 1,
  use: {
    baseURL: process.env.CRE_WEB_TEST_URL || "http://127.0.0.1:3000",
    channel: process.env.CRE_TEST_BROWSER_CHANNEL || undefined,
    launchOptions: { args: ["--enable-unsafe-swiftshader"] },
    trace: "retain-on-failure",
  },
});
