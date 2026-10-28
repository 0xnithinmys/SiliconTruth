"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import LiveRun from "./LiveRun";
import UploadForm, { type StartedRun } from "./UploadForm";

/**
 * Holds the one piece of state the page has: whether a run has been started.
 *
 * Form first, then the same three panes the recorded replays use. Kept in one
 * client component so starting a run does not navigate — the run lives in a
 * process on the server and a reload would lose the handle to it.
 */
export default function LiveWorkspace({
  liveAvailable,
  unavailableReason,
}: {
  liveAvailable: boolean;
  unavailableReason?: string;
}) {
  const [run, setRun] = useState<StartedRun | null>(null);

  if (run) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <LiveRun runId={run.id} chip={run.chip} onReset={() => setRun(null)} />
      </div>
    );
  }

  return (
    <div className="shell w-full py-12 sm:py-16">
      <Link
        href="/"
        className="inline-flex items-center gap-1.5 text-sm text-slate-500 transition-colors hover:text-slate-900"
      >
        <ArrowLeft className="size-3.5" />
        Back
      </Link>

      <h1 className="mt-6 max-w-3xl text-balance text-3xl font-semibold tracking-tight text-slate-900">
        Run it on your own manual
      </h1>
      <p className="mt-3 max-w-2xl text-lg leading-relaxed text-slate-600">
        Give it the PDF and the pages. It renders each page, asks the model
        only for what is printed there, proves the arithmetic with an SMT
        solver, and refuses to generate code from any register it could not
        prove.
      </p>

      {/* Form beside the explanation, rather than stacked above it.
          Stacked, the form was a 672px column against 1390px of header, so
          the page's left edge lined up and its right edge did not — half the
          shell was empty and the steps pushed the first input below the
          fold. Side by side, both columns end where the header ends. */}
      <div className="mt-10 grid gap-x-12 gap-y-10 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 max-w-2xl">
          <UploadForm
            onStarted={setRun}
            disabled={!liveAvailable}
            disabledReason={unavailableReason}
          />
        </div>

        <aside className="min-w-0">
          <h2 className="text-sm font-semibold text-slate-900">
            What happens when you press it
          </h2>
          <ol className="mt-4 space-y-3.5 border-l-2 border-slate-200 pl-5">
            {STEPS.map(([title, body], i) => (
              <li key={title} className="relative">
                <span className="absolute -left-[1.6875rem] flex size-5 items-center justify-center rounded-full bg-slate-900 text-[0.625rem] font-semibold text-white">
                  {i + 1}
                </span>
                <p className="text-sm font-medium text-slate-900">{title}</p>
                <p className="mt-0.5 text-sm leading-relaxed text-slate-600">
                  {body}
                </p>
              </li>
            ))}
          </ol>
          <p className="mt-5 rounded-lg border border-slate-200 bg-white p-3 text-xs leading-relaxed text-slate-500">
            Reading the pages takes about 40 seconds before the first event
            appears, because the run is only recorded once every page has been
            read. The log streams in the meantime.
          </p>
        </aside>
      </div>
    </div>
  );
}

const STEPS: [string, string][] = [
  [
    "Reads the page",
    "Only printed values: names, bit numbers, hex strings. No arithmetic is asked of the model.",
  ],
  [
    "Proves the numbers",
    "Z3 checks the addresses, the bit widths and the reserved bits. A register that fails reaches no generator.",
  ],
  [
    "Writes the driver",
    "SVD register map, C and Rust HAL, and a simulated chip to run it against.",
  ],
  [
    "Executes it",
    "Compiled with -Werror, booted in Renode, and every bus write judged against the datasheet.",
  ],
];
