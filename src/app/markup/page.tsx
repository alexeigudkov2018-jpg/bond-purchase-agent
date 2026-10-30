import type { Metadata } from "next";
import { MarkupDesk } from "@/components/markup-desk";

export const metadata: Metadata = {
  title: "Регрессивная наценка",
  description: "Шкала наценки по закупочной цене с целью валовой маржи 23–27% по деньгам.",
};

export default function MarkupPage() {
  return <MarkupDesk />;
}
