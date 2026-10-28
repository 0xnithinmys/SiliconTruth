"use client";

import RegisterStrip from "./RegisterStrip";
import type { BitMap } from "@/lib/bitfields";
import type { MmioTransaction } from "@/lib/types";

/**
 * The whole peripheral, bit by bit, with the driver's own writes on it.
 *
 * Two things that were only ever text now sit in one picture: the register
 * layout the gates proved, and which of those registers the executed driver
 * actually touched. Reading the mono trace told you `0x40011004` was written;
 * it did not tell you that address is CR2, nor what CR2 is made of.
 *
 * What is deliberately NOT drawn: a time axis. The errata delay is measured
 * in executed instructions, and the peripheral model does not print that
 * count — it only uses it to decide. Drawing a timeline would mean inventing
 * the spacing, which is the one thing this project must never do in a figure
 * about verification.
 */
export default function RegisterMapFigure({
  maps,
  transactions = [],
  baseAddress,
  unverifiedNames = [],
}: {
  maps: BitMap[];
  transactions?: MmioTransaction[];
  baseAddress?: number | null;
  unverifiedNames?: string[];
}) {
  if (maps.length === 0) return null;

  // Writes per register, by offset, so the badge counts real accesses rather
  // than guessing from the register list.
  const touched = new Map<number, { writes: number; reads: number; failed: boolean }>();
  for (const t of transactions) {
    const e = touched.get(t.offset) ?? { writes: 0, reads: 0, failed: false };
    if (t.kind === "WRITE") e.writes += 1;
    else e.reads += 1;
    if (t.verdict === "FAIL") e.failed = true;
    touched.set(t.offset, e);
  }

  return (
    <div className="space-y-5">
      {maps.map((m) => {
        const hit = touched.get(m.offset);
        return (
          <div key={`${m.register}-${m.offset}`}>
            <RegisterStrip
              map={m}
              baseAddress={baseAddress}
              verified={!unverifiedNames.includes(m.register)}
            />
            {hit && (
              <p className="mt-1.5 flex items-center gap-1.5 text-xs text-slate-600">
                <span
                  className={[
                    "inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium ring-1",
                    hit.failed
                      ? "bg-red-50 text-red-700 ring-red-200"
                      : "bg-emerald-50 text-emerald-700 ring-emerald-200",
                  ].join(" ")}
                >
                  {hit.failed ? <Cross /> : <Tick />}
                  {hit.failed ? "rejected by the chip" : "accepted by the chip"}
                </span>
                the driver made{" "}
                {hit.writes > 0 && (
                  <span className="font-medium text-slate-900">
                    {hit.writes} write{hit.writes === 1 ? "" : "s"}
                  </span>
                )}
                {hit.writes > 0 && hit.reads > 0 && " and "}
                {hit.reads > 0 && (
                  <span className="font-medium text-slate-900">
                    {hit.reads} read{hit.reads === 1 ? "" : "s"}
                  </span>
                )}{" "}
                here
              </p>
            )}
            {!hit && transactions.length > 0 && (
              <p className="mt-1.5 text-xs text-slate-400">
                never accessed by the driver
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* Icons, so a status never rests on hue: red and green are 4.1 ΔE apart
   under deuteranopia. */
function Tick() {
  return (
    <svg viewBox="0 0 10 10" className="size-2.5" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <path d="M1.5 5.5 4 8l4.5-6" />
    </svg>
  );
}

function Cross() {
  return (
    <svg viewBox="0 0 10 10" className="size-2.5" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <path d="M2 2l6 6M8 2l-6 6" />
    </svg>
  );
}
