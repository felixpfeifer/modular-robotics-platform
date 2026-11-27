import { expect, test } from "@playwright/test";
for (const width of [1440, 390]) {
  test(`demo telemetry changes and holds at ${width}px`, async ({ page, request }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const initial = await (await request.get("/api/v1/status")).json();
    expect(initial.mode).toBe("demo");
    expect(initial.runtime.active_episode_id).toBeFalsy();
    if (!initial.projects.length)
      await request.post("/api/v1/projects", { data: { name: "Telemetry demo" } });
    await request.post("/api/v1/cell/down", { data: {} });
    try {
      await page.goto("/");
      if (width < 600) await page.getByRole("button", { name: "Open navigation" }).click();
      await page.getByRole("list").getByRole("button", { name: "Record", exact: true }).click();
      if (width < 600)
        await expect(page.getByRole("button", { name: "Projects", exact: true })).toBeHidden();
      await page.getByRole("button", { name: "Start cell", exact: true }).click();
      await page.getByRole("button", { name: "Enable teleop", exact: true }).click();
      const telemetry = page.getByRole("region", { name: "Joint motion" });
      await expect(telemetry.getByText("Follower: Simulated")).toBeVisible();
      await expect(telemetry.getByText("Command: Simulated")).toBeVisible();
      await expect(page.getByText("Waiting for joint readings.")).toHaveCount(0);
      await expect(telemetry.locator(".recharts-line-curve")).toHaveCount(6);
      const before = await (await request.get("/api/v1/status")).json();
      await expect
        .poll(async () => {
          const next = await (await request.get("/api/v1/status")).json();
          return next.runtime.robot_data.Follower.positions;
        })
        .not.toEqual(before.runtime.robot_data.Follower.positions);
      await expect(telemetry.locator(".recharts-line-curve")).toHaveCount(6);
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({
        path: testInfo.outputPath(`demo-record-${width}.png`),
        fullPage: true,
      });
      if (width < 600) await page.getByRole("button", { name: "Open navigation" }).click();
      await page.getByRole("list").getByRole("button", { name: "Deploy", exact: true }).click();
      if (width < 600)
        await expect(page.getByRole("button", { name: "Projects", exact: true })).toBeHidden();
      await expect(telemetry.getByText("Follower: Simulated")).toBeVisible();
      await expect(page.getByRole("button", { name: "Give control to policy" })).toBeDisabled();
      await expect(telemetry.locator(".recharts-line-curve")).toHaveCount(6);
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({
        path: testInfo.outputPath(`demo-deploy-${width}.png`),
        fullPage: true,
      });
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      ).toBeTruthy();
      await request.post("/api/v1/control", { data: { source: "none" } });
      await expect(telemetry.getByText("Command: Inactive")).toBeVisible();
      const held = await (await request.get("/api/v1/status")).json();
      await page.reload();
      const next = await (await request.get("/api/v1/status")).json();
      expect(next.runtime.robot_data.Follower.positions).toEqual(
        held.runtime.robot_data.Follower.positions,
      );
      expect(next.runtime.robot_data.Follower.velocities).toEqual([0, 0, 0, 0, 0, 0]);
    } finally {
      await request.post("/api/v1/cell/down", { data: {} });
    }
  });
}
test("real demo backend: create project, record and see the result", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByRole("button", { name: "Projects", exact: true }).click();
  await page.getByRole("button", { name: "New project" }).click();
  await page.getByLabel("Project name").fill("Browser test project");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.getByText("Project created.")).toBeVisible();
  await page.getByRole("button", { name: "Record", exact: true }).click();
  await page.getByRole("button", { name: "Start cell" }).click();
  await page.getByRole("button", { name: "Enable teleop" }).click();
  await page.getByRole("button", { name: "Start episode" }).click();
  await expect(page.getByText("Recording in progress")).toBeVisible();
  await page.getByRole("button", { name: "Success" }).click();
  await expect(page.getByText("Episode marked success.")).toBeVisible();
  await page.getByRole("button", { name: "Overview", exact: true }).click();
  await expect(page.getByText("Recent sessions")).toBeVisible();
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await expect(page.getByText(/Export is currently unavailable/)).toBeVisible();
  expect(errors).toEqual([]);
});

test("real demo backend: refusal rules and persistence", async ({ page, request }) => {
  // The demo backend is shared by the tests in this file; start from a stopped cell.
  await request.post("/api/v1/cell/down", { data: {} });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByRole("button", { name: "Projects", exact: true }).click();
  await page.getByRole("button", { name: "New project" }).click();
  await page.getByLabel("Project name").fill("Persistence project");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.getByText("Project created.")).toBeVisible();

  await page.getByRole("button", { name: "Record", exact: true }).click();
  // Nothing can be recorded, and teleop cannot be enabled, until the cell runs.
  await expect(page.getByRole("button", { name: /Start episode/ })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Enable teleop" })).toBeDisabled();
  await page.getByRole("button", { name: /Start episode/ }).click();
  await expect(page.getByRole("alert")).toContainText(/cell|teleop/i);

  await page.getByRole("button", { name: "Start cell" }).click();
  await page.getByRole("button", { name: "Enable teleop" }).click();
  await page.getByRole("button", { name: /Start episode/ }).click();
  await expect(page.getByText("Recording in progress")).toBeVisible();

  // State is owned by the backend, so a reload shows the same live recording.
  await page.reload();
  await page.getByRole("list").getByRole("button", { name: "Record", exact: true }).click();
  await expect(page.getByText("Recording in progress")).toBeVisible();
  await expect(page.getByRole("button", { name: /Start episode/ })).toBeDisabled();

  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByText("Ready to record")).toBeVisible();
  await page.getByRole("button", { name: "Stop cell" }).click();
  await expect(page.getByText("Cell stopped.")).toBeVisible();
  await expect(page.getByText("Camera is offline")).toBeVisible();
  expect(errors).toEqual([]);
});
