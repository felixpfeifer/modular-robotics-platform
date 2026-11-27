import { defineConfig, devices } from "@playwright/test";
const real = process.env.MRP_E2E_REAL === "1";
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["junit", { outputFile: "test-results/e2e.xml" }]] : "list",
  use: { baseURL: "http://127.0.0.1:4173", trace: "retain-on-failure" },
  projects: [
    { name: "mock", testMatch: "mock.spec.ts", use: { ...devices["Desktop Chrome"] } },
    { name: "real", testMatch: "real.spec.ts", use: { ...devices["Desktop Chrome"] } },
  ].filter((project) => real || project.name !== "real"),
  webServer: [
    ...(real
      ? [
          {
            command: "python3 tests/demo_server.py",
            port: 18088,
            reuseExistingServer: false,
            timeout: 30000,
          },
        ]
      : []),
    {
      command:
        "MRP_PROXY_TARGET=http://127.0.0.1:18088 yarn vite --host 127.0.0.1 --port 4173 --strictPort",
      port: 4173,
      reuseExistingServer: false,
      timeout: 30000,
    },
  ],
});
