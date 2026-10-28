"use client";

import { useState } from "react";

import CodeDiffPane from "./CodeDiffPane";
import EvidencePane from "./EvidencePane";
import PagePane from "./PagePane";
import ProofPane from "./ProofPane";
import type { PageIndex } from "@/lib/pages";
import type { MmioTransaction, RunEvent, Z3Audit } from "@/lib/types";

/** The 3-pane workbench. Every pane is a client component; the server
 *  component above only reads fixtures and passes props down. */
export default function Workbench({
  chip,
  peripheral,
  events,
  z3,
  artifacts,
  transactions,
  baseAddress,
  unverified,
  pages,
}: {
  chip: string;
  peripheral: string;
  events: RunEvent[];
  z3: Z3Audit | null;
  artifacts: Record<string, string>;
  transactions: MmioTransaction[];
  baseAddress: number;
  unverified: string[];
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
          <EvidencePane events={events} chip={chip} peripheral={peripheral} />
        )}
      </aside>
      <main className="min-h-0 border-neutral-800 lg:border-r">
        <CodeDiffPane artifacts={artifacts} />
      </main>
      <aside className="min-h-0">
        <ProofPane
          z3={z3}
          transactions={transactions}
          baseAddress={baseAddress}
          unverified={unverified}
          selected={selected}
          onSelect={setSelected}
        />
      </aside>
    </div>
  );
}
