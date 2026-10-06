import { execFile } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";

const exec = promisify(execFile);
const root = process.cwd();

async function readPackage() {
  const raw = await readFile(path.join(root, "data/latest_package.json"), "utf8");
  return JSON.parse(raw);
}

export async function GET() {
  try {
    return Response.json(await readPackage());
  } catch {
    return Response.json({ error: "Пакет ещё не собран" }, { status: 404 });
  }
}

export async function POST(request: Request) {
  const body = await request.json().catch(() => ({}));
  if (body.inputs) {
    await writeFile(
      path.join(root, "data/inputs.json"),
      JSON.stringify(body.inputs, null, 2),
      "utf8",
    );
  }
  const args = ["-m", "engine"];
  if (body.refresh) args.push("--refresh");
  try {
    await exec("python3", args, { cwd: root, timeout: 180_000 });
  } catch (error) {
    const stderr = error instanceof Error ? error.message : "сборка не удалась";
    return Response.json({ error: stderr }, { status: 500 });
  }
  return Response.json(await readPackage());
}
