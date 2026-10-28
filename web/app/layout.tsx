import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import "./globals.css";

const geist = Geist({ subsets: ["latin"], variable: "--font-sans" });
const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono" });

export const metadata: Metadata = {
  title: "SiliconTruth",
  description:
    "Turns a chip's PDF manual into driver code, then proves the code matches the page it came from.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // Fixed dark. This is a tool, it is shown on a projector, and a theme
    // toggle is one more thing to explain in a 90-second demo.
    <html lang="en" className={cn("dark", geist.variable, geistMono.variable)}>
      <body className="min-h-screen font-sans antialiased">
        <header className="flex h-14 items-center justify-between border-b px-4">
          <Link href="/" className="flex items-baseline gap-2.5">
            <span className="font-semibold tracking-tight">SiliconTruth</span>
            <span className="hidden text-sm text-muted-foreground sm:inline">
              Chip manual to checked driver code
            </span>
          </Link>
          <Badge variant="outline" className="text-muted-foreground">
            Live demo, no sign-in
          </Badge>
        </header>
        {children}
      </body>
    </html>
  );
}
