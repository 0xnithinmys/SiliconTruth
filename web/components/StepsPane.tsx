"use client";

import { ScrollArea } from "@/components/ui/scroll-area";
import type { RunEvent } from "@/lib/types";
import { stepLabel } from "@/lib/wording";

/**
 * The fallback for the left column when a run has no page captures.
 *
 * It shows what the run actually did, in order, in plain words. A pane that
 * invents a page it does not have would be worse than one that says it has
 * none.
 */
export default function StepsPane({
  events,
  chip,
  peripheral,
}: {
  events: RunEvent[];
  chip: string;
  peripheral: string;
}) {
  return (
    <ScrollArea className="h-full">
      <div className="space-y-4 p-4">
        <div>
          <h2 className="text-sm font-semibold">What happened</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            This run started from an already-read register map, so there are no
            page images to show. Every step it did run is listed below.
          </p>
          <p className="mt-2 font-mono text-xs text-muted-foreground">
            {chip} / {peripheral}
          </p>
        </div>

        <ol className="space-y-1.5">
          {events.map((e, i) => (
            <li key={i} className="flex gap-3 text-sm">
              <span className="w-14 shrink-0 text-right font-mono text-xs text-muted-foreground">
                {e.t_ms.toFixed(0)} ms
              </span>
              <span className={e.kind === "error" ? "text-red-600" : undefined}>
                {stepLabel(String(e.kind))}
                {e.register ? (
                  <span className="ml-1.5 font-mono text-xs text-muted-foreground">
                    {String(e.register)}
                  </span>
                ) : null}
                {e.artifact ? (
                  <span className="ml-1.5 font-mono text-xs text-muted-foreground">
                    {String(e.artifact)}
                  </span>
                ) : null}
              </span>
            </li>
          ))}
        </ol>
      </div>
    </ScrollArea>
  );
}
