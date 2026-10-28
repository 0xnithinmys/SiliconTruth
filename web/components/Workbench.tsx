"use client";

import { useState } from "react";

import ChecksPane from "./ChecksPane";
import CodePane from "./CodePane";
import PagePane from "./PagePane";
import StepsPane from "./StepsPane";
import { Badge } from "@/components/ui/badge";
import type { PageIndex } from "@/lib/pages";
import { checkScore, type RunSummary } from "@/lib/run";
import type { MmioTransaction, RunEvent } from "@/lib/types";

/**
 * The three panes, left to right in the order the work happened: the page it
 * read, the code it wrote, the checks that ran. Each column is labelled,
 * because three unlabelled panes of monospace is the fastest way to lose a
 * visitor who has never seen a register map.
 */
export default function Workbench({
  chip,
  events,
  summary,
  artifacts,
  transactions,
  pages,
}: {
  chip: string;
  events: RunEvent[];
  summary: RunSummary;
  artifacts: Record<string, string>;
  transactions: MmioTransaction[];
  pages: PageIndex | null;
}) {
  // Selecting a register in one pane highlights it in the other. The state
  // lives here because it is shared; neither pane owns it.
  const [selected, setSelected] = useState<string | null>(null);
  const { passed, total } = checkScore(summary.gates);
  const allPassed = passed === total;
  const anyFailed = summary.gates.some((g) => g.status === "fail");

  return (
    // Full viewport height on a wide screen, where three columns fit side by
    // side. On a phone the columns stack, so each gets its own scrollable
    // height instead of being clipped by a viewport-tall parent.
    <div className="flex min-h-0 flex-col lg:h-[calc(100vh-3.5rem)]">
      <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-3">
        <div className="flex items-baseline gap-2">
          <h1 className="font-mono text-sm font-semibold">{chip}</h1>
          <span className="font-mono text-sm text-muted-foreground">
            {summary.peripheral}
          </span>
        </div>
        <Badge
          className={
            anyFailed
              ? "bg-red-500/15 text-red-300"
              : allPassed
                ? "bg-emerald-500/15 text-emerald-300"
                : "bg-amber-500/15 text-amber-200"
          }
        >
          {anyFailed
            ? "A check failed"
            : `${passed} of ${total} checks passed`}
        </Badge>
        <p className="text-sm text-muted-foreground">
          {/* An older fixture recorded no reads at all. Saying "0 registers
              read" beside a driver that clearly has three is worse than
              saying where this run started. */}
          {summary.registers.length > 0
            ? `${summary.registers.length} register${
                summary.registers.length === 1 ? "" : "s"
              } read from the PDF, in ${summary.durationMs.toFixed(0)} ms.`
            : `Started from a register map that had already been read. ${summary.durationMs.toFixed(
                0,
              )} ms.`}
        </p>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[23rem_1fr_27rem]">
        <section className="flex h-[70vh] min-h-0 flex-col border-b lg:h-auto lg:border-b-0 lg:border-r">
          <PaneHeading step="1" title="What it read" />
          <div className="min-h-0 flex-1">
            {pages ? (
              <PagePane index={pages} selected={selected} onSelect={setSelected} />
            ) : (
              // No recorded pages: show the steps instead of an empty page
              // frame.
              <StepsPane
                events={events}
                chip={chip}
                peripheral={summary.peripheral}
              />
            )}
          </div>
        </section>

        <section className="flex h-[70vh] min-h-0 flex-col border-b lg:h-auto lg:border-b-0 lg:border-r">
          <PaneHeading step="2" title="What it wrote" />
          <div className="min-h-0 flex-1">
            <CodePane artifacts={artifacts} />
          </div>
        </section>

        <section className="flex h-[70vh] min-h-0 flex-col lg:h-auto">
          <PaneHeading step="3" title="Why you can trust it" />
          <div className="min-h-0 flex-1">
            <ChecksPane
              summary={summary}
              transactions={transactions}
              selected={selected}
              onSelect={setSelected}
            />
          </div>
        </section>
      </div>
    </div>
  );
}

function PaneHeading({ step, title }: { step: string; title: string }) {
  return (
    <div className="flex shrink-0 items-center gap-2 border-b bg-muted/30 px-4 py-2">
      <span className="flex size-4.5 items-center justify-center rounded-full bg-foreground/10 text-[10px] font-semibold text-foreground/70">
        {step}
      </span>
      <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </h2>
    </div>
  );
}
