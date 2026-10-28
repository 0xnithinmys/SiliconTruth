"use client";

import type { Gate, GateStatus, RunSummary } from "@/lib/pipeline";
import type { MmioTransaction } from "@/lib/types";

const hex = (n: number, w = 8) => "0x" + n.toString(16).toUpperCase().padStart(w, "0");

/**
 * The right pane: the gate scorecard, the UNVERIFIED callout, the errata that
 * were linked, and the MMIO bus trace. These are the things that PROVE
 * something, so if the UI has to be cut back, this pane and the PDF overlay
 * are what survive.
 *
 * Every number here is read from a recorded event. The earlier version
 * printed "bitfield overlaps: 0" and "width conservation: 32/32 bits" as
 * literals and showed one gate when there are four, which made a passing
 * scorecard say nothing about the run that produced it.
 */
export default function ProofPane({
  summary,
  transactions,
  selected,
  onSelect,
}: {
  summary: RunSummary;
  transactions: MmioTransaction[];
  selected?: string | null;
  onSelect?: (register: string) => void;
}) {
  const { gates, baseAddress } = summary;
  const failed = gates.filter((g) => g.status === "fail");
  const passed = gates.filter((g) => g.status === "pass");
  const trapped = transactions.find((t) => t.verdict === "FAIL");
  const unverified = summary.registers.filter((r) => !r.verified);

  // The badge never claims more than the gates do. "All gates passed" is only
  // true when none is missing, and a missing gate is counted, not hidden.
  const tone = failed.length > 0 || trapped ? "bad" : passed.length === gates.length ? "good" : "partial";
  const label =
    trapped ? "MMIO TRAP"
    : failed.length > 0 ? `${failed.length} GATE${failed.length > 1 ? "S" : ""} FAILED`
    : passed.length === gates.length ? "ALL GATES PASSED"
    : `${passed.length} OF ${gates.length} GATES PASSED`;

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-4 text-sm">
      <div
        className={`rounded-lg px-4 py-3 text-center text-base font-semibold tracking-wide ${
          tone === "good"
            ? "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/40"
            : tone === "partial"
              ? "bg-amber-500/15 text-amber-200 ring-1 ring-amber-500/40"
              : "bg-red-500/15 text-red-300 ring-1 ring-red-500/40"
        }`}
      >
        {label}
      </div>

      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-neutral-400">
          Verification gates
        </h3>
        <div className="space-y-2">
          {gates.map((g) => <GateCard key={g.id} gate={g} />)}
        </div>
      </section>

      {unverified.length > 0 && (
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-amber-400">
            Unverified — excluded from codegen
          </h3>
          {/* Surfaced loudly on purpose. A visible gap beats a silent wrong
              offset, and a system that knows what it does not know reads as
              engineering maturity. */}
          <ul className="space-y-1 rounded-lg bg-amber-500/10 p-3 font-mono text-xs text-amber-200 ring-1 ring-amber-500/30">
            {unverified.map((r) => (
              <li key={r.register}>
                {r.register} @ +{hex(r.offset, 3)} (page {r.page})
              </li>
            ))}
          </ul>
        </section>
      )}

      {(summary.errataApplied.length > 0 || summary.errataRejected.length > 0) && (
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-neutral-400">
            Errata linked
          </h3>
          <div className="space-y-1 rounded-lg bg-neutral-900 p-3 font-mono text-xs">
            {summary.errataApplied.map((e) => (
              <p key={e.errata_id} className="text-emerald-300">
                + [{e.errata_id}] {e.register} · {e.constraint}{" "}
                <span className="text-neutral-500">p{e.page}</span>
              </p>
            ))}
            {/* Rejections are shown too: an erratum the linker refused is
                evidence the linker is scoped, not evidence of nothing. */}
            {summary.errataRejected.map((r) => (
              <p key={r} className="text-neutral-500">− {r}</p>
            ))}
          </div>
        </section>
      )}

      <section className="flex-1">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-neutral-400">
          Renode MMIO bus trace
        </h3>
        {transactions.length === 0 ? (
          <p className="text-neutral-500">no transactions recorded</p>
        ) : (
          <div className="overflow-x-auto rounded-lg bg-neutral-900 p-3 font-mono text-xs leading-relaxed">
            {transactions.map((t, i) => {
              // Selecting a register on the page highlights the bus
              // transactions it produced, which is the link between "this
              // is where we read it" and "this is what it did on the bus".
              const active =
                selected != null &&
                t.register.toUpperCase() === selected.toUpperCase();
              return (
                <button
                  key={i}
                  type="button"
                  onClick={() => onSelect?.(t.register)}
                  className={[
                    "block w-full cursor-pointer rounded px-1 text-left",
                    active ? "bg-emerald-400/15 ring-1 ring-emerald-400/40" : "",
                    t.verdict === "FAIL" ? "text-red-400" : "text-neutral-300",
                  ].join(" ")}
                >
                  {t.kind.padEnd(5)}{" "}
                  {/* Without a recorded base address this shows the offset,
                      not an invented absolute address. */}
                  {baseAddress === null
                    ? `+${hex(t.offset, 3)}`
                    : hex(baseAddress + t.offset)}{" "}
                  {"->"} {hex(t.value)}{" "}
                  <span
                    className={
                      t.verdict === "FAIL" ? "text-red-400" : "text-emerald-400"
                    }
                  >
                    [{t.verdict}]
                  </span>
                  {t.note ? ` ${t.note}` : ""}
                </button>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}

const TONE: Record<GateStatus, { dot: string; text: string; mark: string }> = {
  pass: { dot: "bg-emerald-400", text: "text-emerald-300", mark: "PASS" },
  fail: { dot: "bg-red-400", text: "text-red-300", mark: "FAIL" },
  unavailable: { dot: "bg-neutral-500", text: "text-neutral-400", mark: "N/A" },
  missing: { dot: "bg-neutral-600", text: "text-neutral-500", mark: "NOT RUN" },
};

function GateCard({ gate }: { gate: Gate }) {
  const tone = TONE[gate.status];
  return (
    <div className="rounded-lg bg-neutral-900 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-xs font-semibold text-neutral-200">
          <span className={`h-1.5 w-1.5 rounded-full ${tone.dot}`} />
          {gate.label}
        </span>
        <span className={`font-mono text-[10px] tracking-wider ${tone.text}`}>
          {tone.mark}
        </span>
      </div>
      <p className="mt-1 text-[11px] leading-snug text-neutral-500">{gate.proves}</p>
      <p className="mt-1 font-mono text-[11px] text-neutral-300">{gate.detail}</p>
      {gate.violations.map((v) => (
        <p key={v} className="mt-1 font-mono text-[11px] text-red-400">{v}</p>
      ))}
    </div>
  );
}
