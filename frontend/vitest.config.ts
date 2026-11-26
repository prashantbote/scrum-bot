import { defineConfig } from "vitest/config";
import path from "node:path";

const root = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));

export default defineConfig({
  esbuild: { jsx: "automatic" },
  resolve: {
    alias: [
      { find: /^@\/(.*)$/, replacement: path.resolve(root, "src/$1") },
      { find: /^@mocks\/(.*)$/, replacement: path.resolve(root, "mocks/$1") },
    ],
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    env: { NEXT_PUBLIC_API_URL: "http://localhost/api/v1", TZ: "Asia/Kolkata" },
    css: false,
  },
});
