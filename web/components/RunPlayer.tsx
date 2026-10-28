"use client";

import { Pause, Play, RotateCcw, SkipForward } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import Workbench from "./Workbench";
import { Button } from "@/components/ui/button";
import type { PageIndex } from "@/lib/pages";
import { summarize } from "@/lib/run";
import { parseTrace } from "@/lib/trace";
import type { RunEvent } from "@/lib/types";
import { stepLabel } from "@/lib/wording";

/** How long each recorded step is held on screen during playback.
 *
 *  Not the real timing. The whole run took 43 ms, which is unwatchable, and
 *  stretching the real gaps proportionally would spend nine tenths of the
 *  playback on one slow step and flash the rest past. So every step gets an
 *  equal beat and the real timestamp is printed beside it. The UI says this
 *  out loud rather than implying the wall clock is real. */
const STEP_MS = 520;

export default function RunPlayer({
  chip,
  events,
  artifacts,
  pages,
}: {
  chip: string;
  events: RunEvent[];
  artifacts: Record<string, string>;
  pages: PageIndex | null;
}) {
  // The run starts finished. A visitor who never presses anything still sees
  // the complete result; pressing play rewinds and shows how it got there.
  const [step, setStep] = useState(events.length);
  const [playing, setPlaying] = useState(false);
  // At rest before anyone has pressed anything the run is already complete,
  // so "Watch it again" would be inviting a repeat of something they have not
  // seen. The label only changes once they have actually watched it.
  const [watched, setWatched] = useState(false);

  const atEnd = step >= events.length;

  useEffect(() => {
    if (!playing) return;
    if (atEnd) {
      setPlaying(false);
      return;
    }
    const t = setTimeout(() => setStep((s) => s + 1), STEP_MS);
    return () => clearTimeout(t);
  }, [playing, step, atEnd]);

  const play = useCallback(() => {
    // Pressing play at the end means "show me again", not "do nothing".
    if (atEnd) {
      setStep(0);
      setWatched(true);
    }
    setPlaying(true);
  }, [atEnd]);

  const visible = useMemo(() => events.slice(0, step), [events, step]);
  const summary = useMemo(() => summarize(chip, visible), [chip, visible]);

  // A file appears when its own artifact event fires, so the code pane fills
  // up as the generator writes, rather than being complete from the start.
  const visibleArtifacts = useMemo(() => {
    if (atEnd) return artifacts;
    const written = new Set(
      visible.filter((e) => e.kind === "artifact").map((e) => String(e.artifact)),
    );
    return Object.fromEntries(
      Object.entries(artifacts).filter(([name]) => written.has(name)),
    );
  }, [artifacts, visible, atEnd]);

  const traceEvent = visible.find((e) => e.kind === "renode_trace");
  const transactions = traceEvent ? parseTrace(String(traceEvent.text ?? "")) : [];

  const current = step > 0 ? events[step - 1] : null;
  const pct = events.length ? (step / events.length) * 100 : 0;

  return (
    <div className="flex min-h-0 flex-col lg:h-[calc(100vh-3.5rem)]">
      <div className="shrink-0 border-b">
        <div className="flex flex-wrap items-center gap-3 px-4 py-2.5">
          <Button size="sm" onClick={playing ? () => setPlaying(false) : play}>
            {playing ? <Pause /> : <Play />}
            {playing ? "Pause" : !atEnd ? "Resume" : watched ? "Watch it again" : "Watch it run"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setPlaying(false);
              setStep(0);
            }}
            disabled={step === 0}
          >
            <RotateCcw /> Restart
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setPlaying(false);
              setStep(events.length);
            }}
            disabled={atEnd}
          >
            <SkipForward /> Skip to the end
          </Button>

          <div className="min-w-0 flex-1">
            <p className="truncate text-sm">
              {current ? (
                <>
                  <span className="text-muted-foreground">
                    Step {step} of {events.length}:{" "}
                  </span>
                  {stepLabel(String(current.kind))}
                  {current.register ? (
                    <span className="ml-1.5 font-mono text-xs">
                      {String(current.register)}
                    </span>
                  ) : null}
                  {current.artifact ? (
                    <span className="ml-1.5 font-mono text-xs">
                      {String(current.artifact)}
                    </span>
                  ) : null}
                  <span className="ml-2 font-mono text-xs text-muted-foreground">
                    at {Number(current.t_ms).toFixed(1)} ms
                  </span>
                </>
              ) : (
                <span className="text-muted-foreground">
                  Ready. Press play to watch the run, step by step.
                </span>
              )}
            </p>
          </div>
        </div>

        <div className="h-0.5 w-full bg-muted">
          <div
            className="h-full bg-emerald-500 transition-[width] duration-200"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      <div className="min-h-0 flex-1">
        <Workbench
          chip={chip}
          events={visible}
          summary={summary}
          artifacts={visibleArtifacts}
          transactions={transactions}
          pages={pages}
          playedSteps={step}
          totalSteps={events.length}
        />
      </div>
    </div>
  );
}
