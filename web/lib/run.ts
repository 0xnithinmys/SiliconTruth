/**
 * The run, as the UI reads it: types, the check list, and the score.
 *
 * Kept free of node:fs on purpose. The panes are client components and import
 * Gate and checkScore from here, so anything that touches the filesystem lives
 * in lib/pipeline.ts instead and only ever runs on the server.
 *
 * This file exists because the UI had drifted from the backend. It showed one
 * check when there are four, a hardcoded "bitfield overlaps: 0" and "width
 * conservation: 32/32 bits" read from nothing, and a fixed base address of
 * 0x40011000 that is wrong for four of the five benchmark chips.
 *
 * Numbers shown to a visitor have to come from the run. Every field below is
 * read from an event or is explicitly absent.
 */
import type { RunEvent } from "./types";
import { GATE_WORDING, type Wording } from "./wording";

export type GateStatus = "pass" | "fail" | "unavailable" | "missing";

/** A check, as the UI shows it. The plain name, the technical name and what
 *  passing rules out all come from lib/wording.ts, so the landing page and
 *  the workbench cannot describe the same check two different ways. */
export interface Gate extends Wording {
  id: string;
  status: GateStatus;
  /** The measured result, in this check's own units. */
  detail: string;
  violations: string[];
}

export interface ExtractedRegister {
  register: string;
  offset: number;
  width: number;
  resetValue: number;
  fields: number;
  page: number;
  verified: boolean;
  maskId: string | null;
}

export interface LinkedErratum {
  errata_id: string;
  title: string;
  register: string;
  constraint: string;
  params: Record<string, string | number>;
  page: number;
}

export interface RunSummary {
  chip: string;
  peripheral: string;
  /** Read from run_start. Never defaulted: a wrong base address renders a
   *  whole MMIO trace at addresses that do not exist. */
  baseAddress: number | null;
  registers: ExtractedRegister[];
  gates: Gate[];
  errataApplied: LinkedErratum[];
  errataRejected: string[];
  pagesRendered: number[];
  durationMs: number;
}

function num(v: unknown, fallback = 0): number {
  return typeof v === "number" ? v : fallback;
}

function strings(v: unknown): string[] {
  return Array.isArray(v) ? v.map((x) => String(x)) : [];
}

/** The most recent event of a kind. Hand-rolled rather than Array.findLast so
 *  the build does not depend on an ES2023 lib setting. */
function last(events: RunEvent[], kind: string): RunEvent | undefined {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].kind === kind) return events[i];
  }
  return undefined;
}

/** Build the gate list from recorded audit events.
 *
 *  A gate with no event is "missing", NOT passing. A stage that did not run
 *  has not been satisfied, and rendering it as green is the single most
 *  dishonest thing this UI could do. */
export function gatesFrom(events: RunEvent[]): Gate[] {
  // The LAST event of each kind, not the first. `extract` audits before it
  // writes the IR and `build` re-audits before it emits, so a completed run
  // holds two z3_audit events. The later verdict is the one that governs the
  // artifacts on disk.
  const z3 = last(events, "z3_audit");
  const names = last(events, "name_audit");
  const grid = last(events, "grid_audit");
  const trace = last(events, "renode_trace");
  const verdict = last(events, "verdict");

  const gates: Gate[] = [];

  gates.push({
    id: "z3",
    ...GATE_WORDING.z3,
    status: !z3 ? "missing" : z3.passed ? "pass" : "fail",
    detail: z3
      ? `${num(z3.registers)} register${num(z3.registers) === 1 ? "" : "s"} proved in ${num(z3.elapsed_ms).toFixed(0)} ms`
      : "This step has not run on this chip.",
    violations: z3 ? strings(z3.violations) : [],
  });

  gates.push({
    id: "names",
    ...GATE_WORDING.names,
    status: !names
      ? "missing"
      : names.status === "unavailable"
        ? "unavailable"
        : names.passed
          ? "pass"
          : "fail",
    detail: !names
      ? "This step has not run on this chip."
      : names.status === "unavailable"
        ? String(names.reason || "This page has no text layer to check against.")
        : `All ${num(names.checked)} names found in the page text`,
    violations: names ? strings(names.violations) : [],
  });

  gates.push({
    id: "grid",
    ...GATE_WORDING.grid,
    status: !grid
      ? "missing"
      : grid.status === "unavailable"
        ? "unavailable"
        : grid.passed
          ? "pass"
          : "fail",
    detail: !grid
      ? "This step has not run on this chip."
      : grid.status === "unavailable"
        ? String(grid.reason || "The bit-number row could not be read, so this check abstained.")
        : "Every setting sits under its printed bit number",
    violations: grid ? strings(grid.violations) : [],
  });

  gates.push({
    id: "renode",
    ...GATE_WORDING.renode,
    status: !trace && !verdict ? "missing" : verdict?.passed ? "pass" : "fail",
    detail:
      !trace && !verdict
        ? "Needs the simulator container deployed. It has never been executed."
        : String(verdict?.reason || "The simulated run was recorded."),
    violations: [],
  });

  return gates;
}


/** How the checks came out, for a one-glance badge. Failures and checks that
 *  never ran are counted separately: calling a failure "not run" would be the
 *  one wrong way to round this off. A check that never ran still counts in the
 *  total, never quietly dropped from it. */
export function checkScore(gates: Gate[]): {
  passed: number;
  failed: number;
  notRun: number;
  total: number;
} {
  return {
    passed: gates.filter((g) => g.status === "pass").length,
    failed: gates.filter((g) => g.status === "fail").length,
    notRun: gates.filter((g) => g.status === "missing" || g.status === "unavailable")
      .length,
    total: gates.length,
  };
}

/** Build the summary from however many events have happened so far.
 *
 *  Pure and synchronous on purpose: the player calls it once per step to
 *  show the run building up, so it must not touch the filesystem or await
 *  anything. */
export function summarize(chip: string, events: RunEvent[]): RunSummary {
  const start = events.find((e) => e.kind === "run_start");
  const end = last(events, "run_end");
  const errata = last(events, "errata_linked");

  const registers: ExtractedRegister[] = events
    .filter((e) => e.kind === "ir_extracted")
    .map((e) => ({
      register: String(e.register ?? "?"),
      offset: num(e.offset),
      width: num(e.width, 32),
      resetValue: num(e.reset_value),
      fields: num(e.fields),
      page: num(e.page, 1),
      verified: Boolean(e.verified),
      maskId: (e.mask_id as string | null) ?? null,
    }));

  const base = start?.base_address;

  return {
    chip,
    peripheral: String(start?.peripheral ?? "?"),
    // null, not a default. A plausible-looking wrong address is worse than
    // an absent one.
    baseAddress: typeof base === "number" && base > 0 ? base : null,
    registers,
    gates: gatesFrom(events),
    errataApplied: ((errata?.applied as LinkedErratum[]) ?? []).map((e) => ({
      ...e,
      params: e.params ?? {},
    })),
    errataRejected: strings(errata?.rejected),
    pagesRendered: events
      .filter((e) => e.kind === "page_render")
      .map((e) => num(e.page, 1)),
    durationMs: num(end?.t_ms),
  };
}
