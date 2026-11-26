import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll, beforeEach } from "vitest";
import { cleanup } from "@testing-library/react";
import { server } from "@mocks/server";
import { resetDb } from "@mocks/db";
import { setExtraHeaders, setTokenProvider } from "@/lib/api/client";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => {
  resetDb();
  setTokenProvider(async () => null);
  setExtraHeaders(() => ({}));
});
afterEach(() => {
  cleanup();
  server.resetHandlers();
});
afterAll(() => server.close());
