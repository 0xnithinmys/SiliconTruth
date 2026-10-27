"use client";

import CodeDiffPane from "./CodeDiffPane";
import EvidencePane from "./EvidencePane";
import ProofPane from "./ProofPane";
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
}: {
  chip: string;
  peripheral: string;
  events: RunEvent[];
  z3: Z3Audit | null;
  artifacts: Record<string, string>;
  transactions: MmioTransaction[];
  baseAddress: number;
  unverified: string[];
}) {
  return (
    <div className="grid h-[calc(100vh-3.5rem)] grid-cols-1 lg:grid-cols-[22rem_1fr_26rem]">
      <aside className="min-h-0 border-neutral-800 lg:border-r">
        <EvidencePane events={events} chip={chip} peripheral={peripheral} />
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
        />
      </aside>
    </div>
  );
}
