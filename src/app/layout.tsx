import type { Metadata } from "next";
import { Literata, Manrope } from "next/font/google";
import "./globals.css";

const serif = Literata({
  variable: "--font-literata",
  subsets: ["latin", "cyrillic"],
});

const sans = Manrope({
  variable: "--font-manrope",
  subsets: ["latin", "cyrillic"],
});

export const metadata: Metadata = {
  title: "Вторничный пакет облигаций",
  description: "Отбор ОФЗ и корпоративных облигаций на 170 000 ₽ каждый вторник.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru">
      <body className={`${serif.variable} ${sans.variable} font-sans antialiased`}>{children}</body>
    </html>
  );
}
