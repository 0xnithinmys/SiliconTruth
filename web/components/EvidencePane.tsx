"use client";

import type { RunEvent } from "@/lib/types";

/**
 * The left pane. Will become the PDF canvas with SAM mask overlays (T-106/107)
 * once an inference provider is reachable and real masks exist. Until then it
 * shows the recorded provenance, so the pane is honest about what it has rather
 * than displaying a fake page.
 */
export default function EvidencePane({
  events,
  chip,
  peripheral,
}: {
  events: RunEvent[];
  chip: string;
  peripheral: string;
}) {
  const masks = events.filter((e) => e.kind === "sam_mask");
  const pages = events.filter((e) => e.kind === "page_render");

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-4 text-sm">
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-neutral-400">
          Source
        </h3>
        <p className="mt-1 font-mono text-neutral-200">
          {chip} / {peripheral}
        </p>
      </div>

      {masks.length === 0 && pages.length === 0 ? (
        <div className="rounded-lg border border-dashed border-neutral-700 p-4 text-neutral-400">
          <p className="font-medium text-neutral-300">No page captures in this run.</p>
          <p className="mt-2 text-xs leading-relaxed">
            This run started from a verified IR rather than from PDFs, so there are no
            SAM masks to overlay. The perception stage needs a reachable inference
            provider; the Z3 gate, the generators and the MMIO oracle do not, which is
            why those panes are populated and this one is not.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {pages.map((p, i) => (
            <div key={i} className="rounded bg-neutral-900 p-2 font-mono text-xs">
              page {String(p.page)} @ {String(p.dpi)} DPI
            </div>
          ))}
          {masks.map((m, i) => (
            <div key={i} className="rounded bg-neutral-900 p-2 font-mono text-xs">
              <span className="text-cyan-400">mask</span> {String(m.mask_id)} p.{String(m.page)}
            </div>
          ))}
        </div>
      )}

      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-neutral-400">
          Run timeline
        </h3>
        <div className="space-y-0.5 font-mono text-xs">
          {events.map((e, i) => (
            <div key={i} className="flex gap-2">
              <span className="w-16 shrink-0 text-right text-neutral-600">
                {e.t_ms.toFixed(1)}ms
              </span>
              <span className={e.kind === "error" ? "text-red-400" : "text-neutral-400"}>
                {e.kind}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
