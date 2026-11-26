#!/usr/bin/env node
/**
 * Generate typed API definitions from the backend's OpenAPI document (README §3 contract).
 *
 *   npm run gen:api            # writes src/lib/api/schema.d.ts
 *   npm run gen:api -- --check # CI: fail if the committed schema is stale
 *
 * Until backend/openapi.json exists, the app uses the hand-written src/lib/api/types.ts.
 */
import { existsSync, readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";

const spec = resolve(import.meta.dirname, "../../backend/openapi.json");
const out = resolve(import.meta.dirname, "../src/lib/api/schema.d.ts");
const check = process.argv.includes("--check");

if (!existsSync(spec)) {
  console.log(`[gen:api] ${spec} not found — backend has not published its OpenAPI spec yet. Using hand-written types.`);
  process.exit(0);
}

const before = existsSync(out) ? readFileSync(out, "utf8") : "";
execFileSync("npx", ["--yes", "openapi-typescript@7", spec, "-o", out], { stdio: "inherit", shell: process.platform === "win32" });
const after = readFileSync(out, "utf8");

if (check && before !== after) {
  console.error("[gen:api] src/lib/api/schema.d.ts was stale. Commit the regenerated file.");
  process.exit(1);
}
console.log("[gen:api] schema.d.ts is up to date.");
