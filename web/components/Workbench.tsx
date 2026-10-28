"use client";

import { useState } from "react";

import ChecksPane from "./ChecksPane";
import CodePane from "./CodePane";
import PagePane from "./PagePane";
import StepsPane from "./StepsPane";
import { Badge } from "@/components/ui/badge";
import { findSvd } from "@/lib/bitfields";
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
  playedSteps,
  totalSteps,
}: {
  chip: string;
  events: RunEvent[];
  summary: RunSummary;
  artifacts: Record<string, string>;
  transactions: MmioTransaction[];
  pages: PageIndex | null;
  /** How far the player has got. Mid-playback the summary is partial, so the
   *  header says "so far" rather than stating a final score that is not one
   *  yet. */
  playedSteps: number;
  totalSteps: number;
}) {
  // Selecting a register in one pane highlights it in the other. The state
  // lives here because it is shared; neither pane owns it.
  const [selected, setSelected] = useState<string | null>(null);
  const { passed, total } = checkScore(summary.gates);
  const allPassed = passed === total;
  const anyFailed = summary.gates.some((g) => g.status === "fail");
  const midRun = playedSteps < totalSteps;

  return (
    // The player owns the page height; this fills whatever it is given. On a
    // phone the columns stack and each gets its own scrollable height instead
    // of being clipped by a viewport-tall parent.
    <div className="flex h-full min-h-0 flex-col bg-white">
      <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-slate-200 px-4 py-3">
        <div className="flex items-baseline gap-2">
          <h1 className="font-mono text-sm font-semibold">{chip}</h1>
          <span className="font-mono text-sm text-muted-foreground">
            {summary.peripheral}
          </span>
        </div>
        <Badge
          className={
            anyFailed
              ? "border-red-200 bg-red-50 text-red-700"
              : allPassed
                ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                : "border-amber-200 bg-amber-50 text-amber-800"
          }
        >
          {anyFailed
            ? "A check failed"
            : midRun
              ? `${passed} of ${total} checks passed so far`
              : `${passed} of ${total} checks passed`}
        </Badge>
        <p className="text-sm text-muted-foreground">
          {/* An older fixture recorded no reads at all. Saying "0 registers
              read" beside a driver that clearly has three is worse than
              saying where this run started. */}
          {summary.registers.length > 0
            ? `${summary.registers.length} register${
                summary.registers.length === 1 ? "" : "s"
              } read from the PDF${
                midRun ? " so far" : `, in ${summary.durationMs.toFixed(0)} ms`
              }.`
            : midRun
              ? "Nothing read yet."
              : `Started from a register map that had already been read. ${summary.durationMs.toFixed(
                  0,
                )} ms.`}
        </p>
      </div>

      {/* minmax(0,1fr), NOT 1fr. A bare `1fr` track is minmax(auto, 1fr) and
          its auto floor is min-content, so the code pane's long lines
          refused to shrink and shoved the third pane 16px past the
          viewport -- the whole workbench scrolled sideways. */}
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[23rem_minmax(0,1fr)_27rem]">
        <section className="flex h-[70vh] min-h-0 flex-col border-b border-slate-200 lg:h-auto lg:border-b-0 lg:border-r">
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

        <section className="flex h-[70vh] min-h-0 flex-col border-b border-slate-200 lg:h-auto lg:border-b-0 lg:border-r">
          <PaneHeading step="2" title="What it wrote" />
          <div className="min-h-0 flex-1">
            <CodePane artifacts={artifacts} midRun={midRun} />
          </div>
        </section>

        <section className="flex h-[70vh] min-h-0 flex-col lg:h-auto">
          <PaneHeading step="3" title="Why you can trust it" />
          <div className="min-h-0 flex-1">
            <ChecksPane
              summary={summary}
              transactions={transactions}
              // Found by extension rather than by name: the file is
              // <chip>.svd, so a hardcoded "usart1.svd" drew nothing for
              // every other chip.
              svd={findSvd(artifacts)}
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
    <div className="flex shrink-0 items-center gap-2 border-b border-slate-200 bg-slate-50 px-4 py-2">
      <span className="flex size-4.5 items-center justify-center rounded-full bg-slate-900 text-[10px] font-semibold text-white">
        {step}
      </span>
      <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </h2>
    </div>
  );
}
