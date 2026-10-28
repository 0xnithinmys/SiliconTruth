"use client";

import { useState } from "react";

import CodeDiffPane from "./CodeDiffPane";
import EvidencePane from "./EvidencePane";
import PagePane from "./PagePane";
import ProofPane from "./ProofPane";
import type { PageIndex } from "@/lib/pages";
import type { RunSummary } from "@/lib/pipeline";
import type { MmioTransaction, RunEvent } from "@/lib/types";

/** The 3-pane workbench. Every pane is a client component; the server
 *  component above only reads fixtures and passes props down. */
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
  return (
    <div className="grid h-[calc(100vh-3.5rem)] grid-cols-1 lg:grid-cols-[22rem_1fr_26rem]">
      <aside className="min-h-0 border-neutral-800 lg:border-r">
        {pages ? (
          <PagePane index={pages} selected={selected} onSelect={setSelected} />
        ) : (
          // No recorded pages: show the provenance text instead of an empty
          // page frame. A pane that invents a page it does not have is worse
          // than one that says it has none.
          <EvidencePane
            events={events}
            chip={chip}
            peripheral={summary.peripheral}
          />
        )}
      </aside>
      <main className="min-h-0 border-neutral-800 lg:border-r">
        <CodeDiffPane artifacts={artifacts} />
      </main>
      <aside className="min-h-0">
        <ProofPane
          summary={summary}
          transactions={transactions}
          selected={selected}
          onSelect={setSelected}
        />
      </aside>
    </div>
  );
}
