import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "SiliconTruth",
  description:
    "Datasheet + errata PDF to a driver proved correct in hardware emulation.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-neutral-950 text-neutral-200 antialiased">
        <header className="flex h-14 items-center justify-between border-b border-neutral-800 px-4">
          <Link href="/" className="flex items-baseline gap-2">
            <span className="font-semibold tracking-tight">SiliconTruth</span>
            <span className="hidden text-xs text-neutral-500 sm:inline">
              PDF + errata &rarr; proved driver
            </span>
          </Link>
          <span className="rounded bg-neutral-800 px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-neutral-400">
            keyless replay
          </span>
        </header>
        {children}
      </body>
    </html>
  );
}
