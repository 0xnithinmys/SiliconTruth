"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * The site header, in whichever box the page below it uses.
 *
 * It has to switch, because the pages do. A reading page is a shell — a
 * centred 80rem block — so the brand must sit on the shell's left edge and
 * the nav on its right. The workbench is full-bleed, because constraining
 * three panes to 80rem leaves the code pane about 400px wide.
 *
 * Hard-coding one of the two put the brand 184px from the pane titles
 * directly beneath it on /replay, which is the same class of mismatch that
 * made the first layout look broken: two boxes that never agree on an edge.
 */
const FULL_BLEED = ["/replay"];

export default function HeaderBar() {
  const pathname = usePathname() ?? "/";
  const fullBleed = FULL_BLEED.some(
    (p) => pathname === p || pathname.startsWith(`${p}/`),
  );

  return (
    <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-white/85 backdrop-blur-sm">
      <div
        className={`${fullBleed ? "gutter" : "shell"} flex h-14 items-center gap-4`}
      >
        <Link href="/" className="flex items-baseline gap-2.5">
          <span className="font-semibold tracking-tight text-slate-900">
            SiliconTruth
          </span>
          <span className="hidden text-sm text-slate-500 sm:inline">
            Chip manual to checked driver code
          </span>
        </Link>
        <nav className="ml-auto flex items-center gap-1">
          <Link
            href="/live"
            className="rounded-lg px-3 py-1.5 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900"
          >
            Run your own PDF
          </Link>
        </nav>
      </div>
    </header>
  );
}
