#!/usr/bin/env node
/**
 * Обёртка: запускает scripts/build_dashboard.py и пробрасывает код выхода.
 * Использование: node scripts/_run_build_dashboard.mjs
 */
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const script = path.join(root, "scripts", "build_dashboard.py");
const result = spawnSync("python3", [script, ...process.argv.slice(2)], {
  cwd: root,
  stdio: "inherit",
  env: process.env,
});

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}
process.exit(result.status ?? 1);
