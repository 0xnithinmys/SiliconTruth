import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import HeaderBar from "@/components/HeaderBar";
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
    // Light, fixed. No `dark` class and no toggle: a theme switch is one more
    // thing to explain in a 90-second demo, and the status colours are only
    // tuned for one background. See the note in globals.css.
    <html lang="en" className={cn(geist.variable, geistMono.variable)}>
      <body className="min-h-screen font-sans antialiased">
        <HeaderBar />
        {children}
      </body>
    </html>
  );
}
