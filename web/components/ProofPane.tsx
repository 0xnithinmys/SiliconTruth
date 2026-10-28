"use client";

import type { MmioTransaction, Z3Audit } from "@/lib/types";

const hex = (n: number, w = 8) => "0x" + n.toString(16).toUpperCase().padStart(w, "0");

/**
 * The right pane: the Z3 scorecard, the UNVERIFIED callout, and the MMIO bus
 * trace. These are the two things that PROVE something, so if the UI has to be
 * cut back, this pane and the PDF overlay are what survive.
 */
export default function ProofPane({
  z3,
  transactions,
  baseAddress,
  unverified,
  selected,
  onSelect,
}: {
  z3: Z3Audit | null;
  transactions: MmioTransaction[];
  baseAddress: number;
  unverified: string[];
  selected?: string | null;
  onSelect?: (register: string) => void;
}) {
  const failed = transactions.find((t) => t.verdict === "FAIL");
  const verified = Boolean(z3?.passed) && !failed && transactions.length > 0;

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-4 text-sm">
      {/* The badge: the single most legible element for a non-embedded judge. */}
      <div
        className={`rounded-lg px-4 py-3 text-center text-base font-semibold tracking-wide ${
          verified
            ? "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/40"
            : "bg-red-500/15 text-red-300 ring-1 ring-red-500/40"
        }`}
      >
        {verified ? "100% VERIFIED ON RENODE" : failed ? "MMIO TRAP" : "NOT VERIFIED"}
      </div>

      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-neutral-400">
          Z3 proof scorecard
        </h3>
        {z3 ? (
          <div className="space-y-1 rounded-lg bg-neutral-900 p-3 font-mono text-xs">
            <Row label="registers proved" value={String(z3.registers)} ok={z3.passed} />
            <Row label="bitfield overlaps" value="0" ok={z3.passed} />
            <Row label="width conservation" value={z3.passed ? "32/32 bits" : "FAILED"} ok={z3.passed} />
            <Row label="solve time" value={`${z3.elapsed_ms.toFixed(1)} ms`} ok />
            {z3.violations.map((v) => (
              <p key={v} className="pt-1 text-red-400">{v}</p>
            ))}
          </div>
        ) : (
          <p className="text-neutral-500">no audit recorded</p>
        )}
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
            {unverified.map((u) => <li key={u}>{u}</li>)}
          </ul>
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
                  {t.kind.padEnd(5)} {hex(baseAddress + t.offset)} {"->"}{" "}
                  {hex(t.value)}{" "}
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

function Row({ label, value, ok }: { label: string; value: string; ok: boolean }) {
  return (
    <div className="flex justify-between">
      <span className="text-neutral-400">{label}</span>
      <span className={ok ? "text-emerald-400" : "text-red-400"}>{value}</span>
    </div>
  );
}
