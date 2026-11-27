import type * as Client from "../../src/api/client";

/** Every request as one call: GETs pass only the path; POSTs and uploads also pass the body. */
export type FakeCall = (path: string, body?: unknown) => unknown;

/**
 * Replaces the HTTP transport so tests see the exact path and body of each request:
 *
 *   vi.mock("../../src/api/client", async (importOriginal) =>
 *     (await import("./apiMock")).fakeClient(await importOriginal(), api));
 */
export function fakeClient(original: typeof Client, call: FakeCall): typeof Client {
  return {
    ...original,
    apiUrl: (path: string) => path,
    get: async <T>(path: string) => (await call(path)) as T,
    post: async <T>(path: string, body: object = {}) => (await call(path, body)) as T,
    upload: async <T>(path: string, file: Blob) => (await call(path, file)) as T,
  };
}
