import { readFile } from "node:fs/promises";
import path from "node:path";
import { Desk } from "@/components/desk";
import { Preview } from "@/components/preview";

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
  const [report, inputs, preview] = await Promise.all([
    readJson("latest_package.json"),
    readJson("inputs.json"),
    readJson("preview_package.json"),
  ]);
  return (
    <>
      <Preview report={preview} />
      <details className="mx-auto max-w-6xl px-4 pb-16 sm:px-6">
        <summary className="cursor-pointer text-sm text-[#8d4b32]">Прогон Московской биржи от 6 октября</summary>
        <Desk report={report} inputs={inputs || {}} />
      </details>
    </>
  );
}
