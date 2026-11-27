import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    testTimeout: 20000,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/unit/**/*.test.{ts,tsx}"],
    reporters: process.env.CI
      ? ["default", ["junit", { outputFile: "test-results/unit.xml" }]]
      : ["default"],
  },
});
