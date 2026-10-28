"use client";

import { Check, CircleSlash, Minus, X } from "lucide-react";
import { useMemo } from "react";

import RegisterMapFigure from "@/components/figures/RegisterMapFigure";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { parseSvd } from "@/lib/bitfields";
import type { Gate, GateStatus, RunSummary } from "@/lib/run";
import type { MmioTransaction } from "@/lib/types";
import { STATUS_WORDING } from "@/lib/wording";

const hex = (n: number, w = 8) => "0x" + n.toString(16).toUpperCase().padStart(w, "0");

const STATUS: Record<
  GateStatus,
  { icon: typeof Check; tint: string; ring: string }
> = {
  pass: { icon: Check, tint: "text-emerald-600", ring: "bg-emerald-100" },
  fail: { icon: X, tint: "text-red-600", ring: "bg-red-100" },
  unavailable: { icon: CircleSlash, tint: "text-slate-400", ring: "bg-slate-100" },
  missing: { icon: Minus, tint: "text-slate-400", ring: "bg-slate-100" },
};

/**
 * What was checked, and what it means.
 *
 * This is the pane the whole project exists for, so it leads with the plain
 * sentence and keeps the technical name beside it. A check that never ran
 * reads "Not run", never green: a stage that did not happen has not been
 * satisfied.
 */
export default function ChecksPane({
  summary,
  transactions,
  svd,
  selected,
  onSelect,
}: {
  summary: RunSummary;
  transactions: MmioTransaction[];
  /** The generated CMSIS-SVD, when the run got far enough to emit one. The
   *  bit maps are drawn from it rather than from the IR events, which record
   *  a field count and not the field list. */
  svd?: string | null;
  selected?: string | null;
  onSelect?: (register: string) => void;
}) {
  const { gates, baseAddress } = summary;
  const unverified = summary.registers.filter((r) => !r.verified);
  const trapped = transactions.some((t) => t.verdict === "FAIL");
  const maps = useMemo(() => (svd ? parseSvd(svd) : []), [svd]);

  return (
    <ScrollArea className="h-full">
      <div className="space-y-6 p-4">
        <section className="space-y-2">
          <h2 className="text-sm font-semibold">What was checked</h2>
          <p className="text-sm text-muted-foreground">
            Nothing the model reported is trusted on its own. Each check below
            tests the output against the page it came from.
          </p>
          <div className="space-y-2 pt-1">
            {gates.map((gate) => (
              <GateRow key={gate.id} gate={gate} />
            ))}
          </div>
        </section>

        {maps.length > 0 && (
          <>
            <Separator />
            <section className="space-y-2">
              <h2 className="text-sm font-semibold">What the registers look like</h2>
              <p className="text-sm text-muted-foreground">
                Every boundary below was read off a table in the PDF and then
                proved before any code was written. Hatched bits are reserved.
                Hover a field for its exact range.
              </p>
              <div className="pt-1">
                <RegisterMapFigure
                  maps={maps}
                  transactions={transactions}
                  baseAddress={baseAddress}
                  unverifiedNames={unverified.map((r) => r.register)}
                />
              </div>
            </section>
          </>
        )}

        {unverified.length > 0 && (
          <>
            <Separator />
            <section className="space-y-2">
              <h2 className="text-sm font-semibold text-amber-300">
                Left out of the code
              </h2>
              <p className="text-sm text-muted-foreground">
                A check rejected these, so nothing was generated for them. A
                visible gap is safer than a wrong register.
              </p>
              <ul className="space-y-1 rounded-lg border border-amber-200 bg-amber-50 p-3 font-mono text-xs text-amber-900">
                {unverified.map((r) => (
                  <li key={r.register}>
                    {r.register}, page {r.page}
                  </li>
                ))}
              </ul>
            </section>
          </>
        )}

        {summary.errataApplied.length > 0 && (
          <>
            <Separator />
            <section className="space-y-2">
              <h2 className="text-sm font-semibold">Known chip bugs handled</h2>
              <p className="text-sm text-muted-foreground">
                Chip makers publish a second PDF listing what the silicon gets
                wrong. These were found there, and the workaround is already in
                the generated driver.
              </p>
              <div className="space-y-2">
                {summary.errataApplied.map((e) => (
                  <Card key={e.errata_id} className="gap-0 py-3">
                    <CardContent className="px-3">
                      <div className="flex items-start justify-between gap-2">
                        <p className="text-sm leading-snug">{e.title}</p>
                        <Badge variant="outline" className="shrink-0 font-mono">
                          {e.register}
                        </Badge>
                      </div>
                      <p className="mt-1 font-mono text-xs text-muted-foreground">
                        erratum {e.errata_id}, page {e.page}
                      </p>
                    </CardContent>
                  </Card>
                ))}
              </div>
              {summary.errataRejected.length > 0 && (
                <p className="text-xs text-muted-foreground">
                  {summary.errataRejected.length} more were found but rejected,
                  because they apply to a different part of the chip.
                </p>
              )}
            </section>
          </>
        )}

        <Separator />
        <section className="space-y-2">
          <h2 className="text-sm font-semibold">
            What the driver did on the simulated chip
          </h2>
          {transactions.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Nothing recorded yet. This is the simulator step, and it needs the
              container deployed.
            </p>
          ) : (
            <>
              <p className="text-sm text-muted-foreground">
                Every value the driver read or wrote, checked against the
                manual. Click a line to highlight that register on the page.
              </p>
              <div className="overflow-x-auto rounded-lg bg-muted/50 p-3 font-mono text-xs leading-relaxed">
                {transactions.map((t, i) => {
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
                        active ? "bg-emerald-100" : "",
                        t.verdict === "FAIL" ? "text-red-700" : "text-slate-700",
                      ].join(" ")}
                    >
                      {t.kind.padEnd(5)}{" "}
                      {/* Without a recorded base address this shows the
                          offset rather than an invented absolute address. */}
                      {baseAddress === null
                        ? `+${hex(t.offset, 3)}`
                        : hex(baseAddress + t.offset)}{" "}
                      {t.register} {hex(t.value)}{" "}
                      <span
                        className={
                          t.verdict === "FAIL" ? "text-red-600" : "text-emerald-600"
                        }
                      >
                        {t.verdict === "FAIL" ? "wrong" : "as documented"}
                      </span>
                      {t.note ? ` ${t.note}` : ""}
                    </button>
                  );
                })}
              </div>
              {trapped && (
                <p className="text-sm text-red-700">
                  One of these did not match the manual, so the driver is not
                  called correct.
                </p>
              )}
            </>
          )}
        </section>
      </div>
    </ScrollArea>
  );
}

function GateRow({ gate }: { gate: Gate }) {
  const tone = STATUS[gate.status];
  const Icon = tone.icon;
  return (
    <Card className="gap-0 py-3">
      <CardContent className="flex items-start gap-3 px-3">
        <span
          className={`mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full ${tone.ring}`}
        >
          <Icon className={`size-3 ${tone.tint}`} aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <p className="text-sm font-medium leading-snug">{gate.plain}</p>
            <span className={`shrink-0 text-xs font-medium ${tone.tint}`}>
              {STATUS_WORDING[gate.status]}
            </span>
          </div>
          <p className="mt-1 text-xs leading-snug text-muted-foreground">
            {gate.proves}
          </p>
          <p className="mt-1.5 text-xs text-foreground/70">{gate.detail}</p>
          {gate.violations.map((v) => (
            <p key={v} className="mt-1 font-mono text-xs text-red-700">
              {v}
            </p>
          ))}
          <p className="mt-1.5 text-[11px] text-muted-foreground/70">
            {gate.technical}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
