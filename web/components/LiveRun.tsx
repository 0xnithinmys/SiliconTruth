"use client";

import { AlertTriangle, CheckCircle2, Loader2, RotateCcw, XCircle } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import Workbench from "./Workbench";
import { Button } from "@/components/ui/button";
import { summarize } from "@/lib/run";
import { parseTrace } from "@/lib/trace";
import type { RunEvent } from "@/lib/types";

/**
 * A run happening NOW, in the same three panes the recorded replays use.
 *
 * Deliberately not a second workbench. The live run and the recorded ones
 * display through exactly the same component, because the Python recorder
 * writes the same JSONL either way. If the live view had its own renderer it
 * would drift, and then "watch it work" and "watch a recording of it working"
 * would stop being the same claim.
 *
 * Polling rather than SSE. The events are appended to a file by a subprocess,
 * so there is nothing to push from; a poll reads whatever has landed. It also
 * survives the server restarting mid-run, which a held-open stream does not.
 */

const POLL_MS = 900;

type Status = "running" | "passed" | "failed";

interface Snapshot {
  id: string;
  chip: string;
  status: Status;
  stage: string;
  exitCode: number | null;
  events: RunEvent[];
  artifacts: Record<string, string>;
  log: string[];
  /** The one sentence worth reading, already pulled out of the log. */
  reason: string | null;
  elapsedMs: number;
}

const STAGE_WORDING: Record<string, string> = {
  extract: "Reading the pages",
  build: "Generating the driver",
  emulate: "Compiling and running it",
};

export default function LiveRun({
  runId,
  chip,
  onReset,
}: {
  runId: string;
  chip: string;
  onReset: () => void;
}) {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Held in a ref so the poll effect does not restart on every tick.
  const stopped = useRef(false);

  const poll = useCallback(async () => {
    try {
      const res = await fetch(`/api/run?id=${encodeURIComponent(runId)}`, {
        cache: "no-store",
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.message ?? `the server returned ${res.status}`);
        stopped.current = true;
        return;
      }
      setSnap(data as Snapshot);
      if (data.status !== "running") stopped.current = true;
    } catch (e) {
      // A single failed poll is not a failed run; keep going and let the
      // next tick recover.
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [runId]);

  useEffect(() => {
    stopped.current = false;
    void poll();
    const t = setInterval(() => {
      if (stopped.current) return;
      void poll();
    }, POLL_MS);
    return () => clearInterval(t);
  }, [poll]);

  // Memoised because `?? []` built a fresh array on every render, which made
  // both useMemos below recompute on every one -- and with a 900ms poll that
  // is summarize() over the whole event list several times a second.
  const events = useMemo(() => snap?.events ?? [], [snap]);
  const summary = useMemo(() => summarize(chip, events), [chip, events]);
  const transactions = useMemo(() => {
    const trace = [...events].reverse().find((e) => e.kind === "renode_trace");
    return trace ? parseTrace(String(trace.text ?? "")) : [];
  }, [events]);

  const running = snap?.status === "running" || !snap;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <LiveHeader
        chip={chip}
        snap={snap}
        running={running}
        error={error}
        onReset={onReset}
      />

      {events.length === 0 ? (
        <Starting stage={snap?.stage} log={snap?.log ?? []} running={running} />
      ) : (
        <div className="min-h-0 flex-1">
          <Workbench
            chip={chip}
            events={events}
            summary={summary}
            artifacts={snap?.artifacts ?? {}}
            transactions={transactions}
            // No recorded page images for an uploaded PDF, so the first pane
            // shows the step log instead. Showing an empty page frame would
            // imply a render that did not happen.
            pages={null}
            // Live, so everything that has arrived has "played". The summary
            // still hedges with "so far" while the run is going, because
            // playedSteps < totalSteps is what drives that wording.
            playedSteps={events.length}
            totalSteps={running ? events.length + 1 : events.length}
          />
        </div>
      )}

      {snap?.status === "failed" && <FailureDetail snap={snap} />}
    </div>
  );
}

function LiveHeader({
  chip, snap, running, error, onReset,
}: {
  chip: string;
  snap: Snapshot | null;
  running: boolean;
  error: string | null;
  onReset: () => void;
}) {
  const seconds = ((snap?.elapsedMs ?? 0) / 1000).toFixed(0);
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-slate-200 bg-white px-4 py-3">
      <div className="flex items-center gap-2.5">
        {running ? (
          <Loader2 className="size-4 animate-spin text-slate-400" />
        ) : snap?.status === "passed" ? (
          <CheckCircle2 className="size-4 text-emerald-600" />
        ) : (
          <XCircle className="size-4 text-red-600" />
        )}
        <span className="font-mono text-sm font-semibold text-slate-900">{chip}</span>
      </div>

      <span className="text-sm text-slate-600">
        {running
          ? `${STAGE_WORDING[snap?.stage ?? "extract"] ?? snap?.stage}…`
          : snap?.status === "passed"
            ? "Finished"
            : `Stopped at ${snap?.stage ?? "?"}`}
        <span className="ml-2 text-slate-400">{seconds}s</span>
      </span>

      {error && (
        <span className="flex items-center gap-1.5 text-sm text-amber-700">
          <AlertTriangle className="size-3.5" />
          {error}
        </span>
      )}

      <div className="ml-auto">
        <Button variant="outline" size="sm" onClick={onReset}>
          <RotateCcw /> New run
        </Button>
      </div>
    </div>
  );
}

function Starting({
  stage, log, running,
}: {
  stage?: string;
  log: string[];
  running: boolean;
}) {
  return (
    <div className="shell w-full py-16">
      <div className="flex items-center gap-3">
        {running && <Loader2 className="size-5 animate-spin text-slate-400" />}
        <h2 className="text-lg font-semibold text-slate-900">
          {STAGE_WORDING[stage ?? "extract"] ?? "Starting"}
        </h2>
      </div>
      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-600">
        Reading a page means rendering it, asking the model only for what is
        printed on it, and then proving the arithmetic before a single line of
        code is written. The first event appears when the first page is
        rendered.
      </p>
      {log.length > 0 && (
        <pre className="mt-6 max-h-64 max-w-4xl overflow-auto rounded-xl border border-slate-200 bg-slate-50 p-4 font-mono text-xs leading-relaxed text-slate-700">
          {log.join("\n")}
        </pre>
      )}
    </div>
  );
}

function FailureDetail({ snap }: { snap: Snapshot }) {
  return (
    <div className="shrink-0 border-t border-red-200 bg-red-50/70 px-4 py-4">
      <p className="flex items-center gap-2 text-sm font-semibold text-red-800">
        <XCircle className="size-4" />
        The run stopped at {snap.stage}
        {snap.exitCode !== null && (
          <span className="font-normal text-red-700">exit {snap.exitCode}</span>
        )}
      </p>
      {snap.reason && (
        <p className="mt-2 max-w-3xl text-sm font-medium leading-relaxed text-red-900">
          {snap.reason}
        </p>
      )}
      <p className="mt-1.5 text-sm leading-relaxed text-red-700">
        Nothing was reported as verified past this point.
      </p>
      {/* Folded away. A traceback is the useful part when the cause is a
          defect and pure noise when it is a typo, and printing it flat put
          forty frames of Python between the reader and the one line that
          told them what to change. */}
      <details className="mt-3 max-w-4xl">
        <summary className="cursor-pointer text-xs font-medium text-red-700 hover:text-red-900">
          What the pipeline printed
        </summary>
        <pre className="mt-2 max-h-56 overflow-auto rounded-lg border border-red-200 bg-white p-3 font-mono text-xs leading-relaxed text-red-900">
          {snap.log.join("\n")}
        </pre>
      </details>
    </div>
  );
}
