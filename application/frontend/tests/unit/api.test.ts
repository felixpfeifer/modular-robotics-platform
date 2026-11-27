import type { AxiosAdapter, InternalAxiosRequestConfig } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

// A real axios instance (so the error interceptor runs) with the network replaced by `adapter`.
type Respond = (config: InternalAxiosRequestConfig) => Promise<unknown>;
const network = vi.hoisted(() => ({
  respond: null as Respond | null,
  sent: [] as InternalAxiosRequestConfig[],
}));
vi.mock("axios", async (importOriginal) => {
  const real = await importOriginal<typeof import("axios")>();
  const create: typeof real.default.create = (config) =>
    real.default.create({
      ...config,
      adapter: ((request: InternalAxiosRequestConfig) => {
        network.sent.push(request);
        return network.respond!(request);
      }) as AxiosAdapter,
    });
  return { ...real, default: { ...real.default, create } };
});

import { AxiosError, AxiosHeaders } from "axios";
import {
  ApiError,
  apiUrl,
  errorMessage,
  get,
  path,
  post,
  upload,
  withQuery,
  wsUrl,
} from "../../src/api/client";

const reply =
  (data: unknown, status = 200) =>
  (config: InternalAxiosRequestConfig) =>
    Promise.resolve({ data, status, statusText: "", headers: {}, config });
const fail = (data: unknown, status: number) => (config: InternalAxiosRequestConfig) =>
  Promise.reject(
    new AxiosError("Request failed", "ERR_BAD_RESPONSE", config, null, {
      data,
      status,
      statusText: "",
      headers: {},
      config,
    }),
  );
const sent = () => network.sent.at(-1)!;

beforeEach(() => {
  network.respond = null;
  network.sent = [];
});

describe("URLs", () => {
  it("joins the base and path with exactly one slash", () => {
    expect(apiUrl("/api/v1/status")).toBe("/api/v1/status");
    expect(apiUrl("api/v1/status")).toBe("/api/v1/status");
  });
  it("uses the WebSocket scheme matching the page", () => {
    expect(wsUrl("/api/v1/telemetry").protocol).toBe("ws:");
  });
  it("encodes interpolated path segments", () => {
    expect(path`/api/v1/projects/${"a b/c"}/rename`).toBe("/api/v1/projects/a%20b%2Fc/rename");
  });
  it("adds a query string and drops undefined values", () => {
    expect(withQuery("/x", { a: 1, b: undefined, c: true })).toBe("/x?a=1&c=true");
    expect(withQuery("/x", { b: undefined })).toBe("/x");
  });
});

describe("requests", () => {
  it("GETs and returns the response data", async () => {
    network.respond = reply({ ok: 1 });
    await expect(get("/a")).resolves.toEqual({ ok: 1 });
    expect(sent()).toMatchObject({ method: "get", url: "/a" });
  });
  it("POSTs an empty JSON object when there is no body, as the backend requires", async () => {
    network.respond = reply({});
    await post("/api/v1/cell/up");
    expect(sent().method).toBe("post");
    expect(sent().data).toBe("{}");
    expect(AxiosHeaders.from(sent().headers).getContentType()).toMatch(/application\/json/);
  });
  it("uploads a file as the raw body with its content type", async () => {
    network.respond = reply({ valid: true });
    const file = new Blob(["x"]);
    await expect(upload("/api/v1/config/validate", file, "application/gzip")).resolves.toEqual({
      valid: true,
    });
    expect(sent().data).toBe(file);
    expect(AxiosHeaders.from(sent().headers).getContentType()).toBe("application/gzip");
  });
});

describe("errors", () => {
  it("surfaces the backend's message and status as an ApiError", async () => {
    network.respond = fail({ error: "Start the cell first." }, 409);
    const error = await post("/x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ message: "Start the cell first.", status: 409 });
  });
  it("falls back to the transport message when the body has no error", async () => {
    network.respond = fail("<html>", 502);
    await expect(get("/x")).rejects.toThrow("Request failed");
  });
  it("reports network failures without a status", async () => {
    network.respond = () => Promise.reject(new AxiosError("Network Error", "ERR_NETWORK"));
    await expect(get("/x")).rejects.toMatchObject({ message: "Network Error", status: undefined });
  });
  it("picks a message for any thrown value", () => {
    expect(errorMessage(new Error("boom"))).toBe("boom");
    expect(errorMessage("nope", "Fallback")).toBe("Fallback");
  });
});
