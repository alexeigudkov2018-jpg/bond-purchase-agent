import { readFile } from "node:fs/promises";
import path from "node:path";
import { Desk } from "@/components/desk";
import { MoexCheck } from "@/components/moex-check";
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
  const [report, inputs, preview, moex] = await Promise.all([
    readJson("latest_package.json"),
    readJson("inputs.json"),
    readJson("preview_package.json"),
    readJson("moex_package.json"),
  ]);
  return (
    <>
      <MoexCheck report={moex} />
      <details className="mx-auto max-w-6xl px-4 pb-8 sm:px-6">
        <summary className="cursor-pointer text-sm text-[#8d4b32]">Предварительный расчёт только по файлу, без биржи</summary>
        <Preview report={preview} />
      </details>
      <details className="mx-auto max-w-6xl px-4 pb-16 sm:px-6">
        <summary className="cursor-pointer text-sm text-[#8d4b32]">Прогон Московской биржи от 6 октября</summary>
        <Desk report={report} inputs={inputs || {}} />
      </details>
    </>
  );
}
