import { readFile } from "node:fs/promises";
import path from "node:path";
import { Desk } from "@/components/desk";

export const dynamic = "force-dynamic";

async function readJson(name: string) {
  try {
    const raw = await readFile(path.join(process.cwd(), "data", name), "utf8");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export default async function Page() {
  const [report, inputs] = await Promise.all([readJson("latest_package.json"), readJson("inputs.json")]);
  return <Desk report={report} inputs={inputs || {}} />;
}
