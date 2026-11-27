import { expect, test } from "@playwright/test";
const status = {
  mode: "demo",
  projects: [
    { id: "p1", name: "First project" },
    { id: "p2", name: "Second project" },
  ],
  sessions: [],
  runtime: { cell_running: false, active_source: "none", checks: [], message: "Start the cell" },
  settings: { hf_token_set: false, hf_namespace: "" },
  export_enabled: true,
};
for (const width of [1440, 390]) {
  test(`robot telemetry renders in recording and inference at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const errors: string[] = [];
    const cameraIds = new Set<string | null>();
    const cameraFrame = Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGPIW9UEAAMkAZu7KdeOAAAAAElFTkSuQmCC",
      "base64",
    );
    page.on("pageerror", (error) => errors.push(error.message));
    await page.routeWebSocket(/\/api\/v1\/camera\?/, (socket) => {
      cameraIds.add(new URL(socket.url()).searchParams.get("camera"));
      socket.send(cameraFrame);
    });
    await page.route("**/api/v1/status", (route) => {
      const stamp = Date.now();
      const joint_names = [
        "shoulder_pan",
        "shoulder_lift",
        "elbow_flex",
        "wrist_flex",
        "wrist_roll",
        "gripper",
      ];
      const sample = (offset: number) => ({
        stamp_ns: stamp * 1000000,
        joint_names,
        positions: joint_names.map(
          (_, index) => Math.sin(stamp / 4000) * 0.3 + index * 0.12 + offset,
        ),
        velocities: joint_names.map(() => 0.1),
        fresh: true,
      });
      return route.fulfill({
        json: {
          ...status,
          mode: "ros",
          agent_configured: true,
          runtime: {
            ...status.runtime,
            cell_running: true,
            active_source: "policy",
            camera_previews: ["overhead", "wrist"],
            robot_data: {
              Follower: sample(0),
              Action: { ...sample(0.05), source: "policy_act" },
              Leader: sample(0.1),
            },
          },
        },
      });
    });
    await page.goto("/");
    for (const name of ["Record", "Deploy"]) {
      if (width < 600) await page.getByRole("button", { name: "Open navigation" }).click();
      await page.getByRole("list").getByRole("button", { name, exact: true }).click();
      if (name === "Record") {
        await expect(page.getByRole("img", { name: "Overhead preview" })).toBeVisible();
        await expect(page.getByRole("img", { name: "Wrist preview" })).toBeVisible();
        expect(cameraIds).toEqual(new Set(["overhead", "wrist"]));
      }
      const telemetry = page.getByRole("region", { name: "Joint motion" });
      await expect(telemetry.getByText("Measured: Live")).toBeVisible();
      await expect(telemetry.locator(".recharts-line-curve")).toHaveCount(6);
      await telemetry.getByRole("combobox", { name: "Plot source" }).click();
      await page.getByRole("option", { name: "Command", exact: true }).click();
      await telemetry.getByRole("button", { name: "Velocity", exact: true }).click();
      await expect(
        telemetry.getByRole("img", { name: "All joints velocity history" }),
      ).toBeVisible();
      await telemetry.getByRole("button", { name: "Zoom in" }).click();
      await expect(telemetry.getByText(/Paused · 6 s window/)).toBeVisible();
      await telemetry.getByRole("button", { name: "Go live" }).click();
      await expect(telemetry.getByText(/Live · 6 s window/)).toBeVisible();
      await telemetry.screenshot({
        path: testInfo.outputPath(`${name.toLowerCase()}-${width}.png`),
      });
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      ).toBeTruthy();
    }
    expect(errors).toEqual([]);
  });
}
test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/status")) return route.fulfill({ json: status });
    if (path.endsWith("/episodes"))
      return route.fulfill({
        json: {
          episodes: [
            {
              id: "episode-one",
              project_id: "p1",
              status: "accepted",
              manifest: { task_id: "pick_up" },
              validation: { valid: true },
            },
          ],
        },
      });
    return route.fulfill({ json: {} });
  });
});
test("navigation, project switching and export selection", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Welcome to MRP Studio" })).toBeVisible();
  await page.getByRole("button", { name: "Dataset", exact: true }).click();
  await page.getByRole("checkbox", { name: /Select episode/ }).check();
  await expect(
    page.getByRole("button", { name: /Export selected recordings \(1\)/ }),
  ).toBeEnabled();
  await page.getByRole("combobox", { name: "Active project" }).click();
  await page.getByRole("option", { name: "Second project" }).click();
  await expect(page.getByText("No accepted recordings yet")).toBeVisible();
  await page.getByRole("combobox", { name: "Active project" }).click();
  await page.getByRole("option", { name: "First project" }).click();
  await expect(page.getByRole("checkbox", { name: /Select episode/ })).not.toBeChecked();
});
test("mobile navigation fits the viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("button", { name: "Record", exact: true }).click();
  await expect(page.getByText("Camera is offline")).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
  ).toBeTruthy();
});
test("connection failure offers a retry", async ({ page }) => {
  await page.unrouteAll({ behavior: "wait" });
  await page.route("**/api/v1/**", (route) => route.abort());
  await page.goto("/");
  await expect(page.getByText("Unable to connect to MRP")).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry connection" })).toBeVisible();
});

test("a refused action shows the backend message and the page stays usable", async ({ page }) => {
  await page.route("**/api/v1/cell/up", (route) =>
    route.fulfill({ status: 409, json: { error: "Docker is not reachable." } }),
  );
  await page.goto("/");
  await page.getByRole("list").getByRole("button", { name: "Record", exact: true }).click();
  await page.getByRole("button", { name: "Start cell" }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Docker is not reachable." }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Start cell" })).toBeEnabled();
  await expect(page.getByText("Camera is offline")).toBeVisible();
});

test("the browser sends a valid, unique request id for each recording", async ({ page }) => {
  const ids: string[] = [];
  await page.unrouteAll({ behavior: "wait" });
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/status"))
      return route.fulfill({
        json: {
          ...status,
          runtime: {
            cell_running: true,
            active_source: "teleop",
            checks: [{ name: "Camera", ready: true, detail: "" }],
            message: "Ready",
          },
        },
      });
    if (path.endsWith("/episodes")) return route.fulfill({ json: { episodes: [] } });
    if (path.endsWith("/sessions")) {
      ids.push(route.request().postDataJSON().request_id);
      return route.fulfill({ status: 409, json: { error: "Already recording." } });
    }
    return route.fulfill({ json: {} });
  });
  await page.goto("/");
  await page.getByRole("list").getByRole("button", { name: "Record", exact: true }).click();
  await expect(page.getByText("Cell running", { exact: true })).toBeVisible();
  await expect(page.getByText("Camera: ready")).toBeVisible();
  for (let i = 0; i < 2; i++) {
    await page.getByRole("button", { name: /Start episode/ }).click();
    await expect(page.getByRole("alert").filter({ hasText: "Already recording." })).toBeVisible();
  }
  expect(ids).toHaveLength(2);
  for (const id of ids) expect(id).toMatch(/^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$/);
  expect(new Set(ids).size).toBe(2);
});

test("settings never display or echo a saved token", async ({ page }) => {
  let sent: unknown;
  await page.route("**/api/v1/settings", async (route) => {
    sent = route.request().postDataJSON();
    return route.fulfill({ json: {} });
  });
  await page.goto("/");
  await page.getByRole("list").getByRole("button", { name: "Settings", exact: true }).click();
  const token = page.getByLabel("Access token");
  await expect(token).toHaveAttribute("type", "password");
  await token.fill("hf_secret");
  await page.getByLabel("Default namespace").fill("lab");
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByText("Settings saved.")).toBeVisible();
  expect(sent).toEqual({ hf_token: "hf_secret", hf_namespace: "lab" });
});

test("no uncaught errors while visiting every page", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  for (const name of ["Projects", "Record", "Dataset", "Settings", "Overview"]) {
    await page.getByRole("list").getByRole("button", { name, exact: true }).click();
  }
  expect(errors).toEqual([]);
});

test("the chosen project survives a reload", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("combobox", { name: "Active project" }).click();
  await page.getByRole("option", { name: "Second project" }).click();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Second project" })).toBeVisible();
});
