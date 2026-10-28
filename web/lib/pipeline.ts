/**
 * The pipeline, read from what the run actually recorded.
 *
 * This file exists because the UI had drifted from the backend. It showed
 * one gate when there are three, a hardcoded "bitfield overlaps: 0" and
 * "width conservation: 32/32 bits" that were never read from anything, a
 * fixed base address of 0x40011000 that is wrong for four of the five
 * benchmark chips, and a hardcoded list of `usart1_*` filenames so a chip
 * whose peripheral is PORTB or PMIC displayed no code at all.
 *
 * Numbers shown to a judge have to come from the run. Every field below is
 * read from an event or is explicitly absent.
 */
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

import type { RunEvent } from "./types";

const FIXTURES = path.join(process.cwd(), "public", "fixtures");

export type GateStatus = "pass" | "fail" | "unavailable" | "missing";

export interface Gate {
  id: string;
  label: string;
  /** What it proves, in one line, for someone who has not read the README. */
  proves: string;
  status: GateStatus;
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
function gatesFrom(events: RunEvent[]): Gate[] {
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
    label: "Z3 arithmetic",
    proves:
      "aligned address, no overlapping fields, every bit accounted for, " +
      "clean reserved reset",
    status: !z3 ? "missing" : z3.passed ? "pass" : "fail",
    detail: z3
      ? `${num(z3.registers)} register(s) proved in ${num(z3.elapsed_ms).toFixed(1)} ms`
      : "not run",
    violations: z3 ? strings(z3.violations) : [],
  });

  gates.push({
    id: "names",
    label: "Name corroboration",
    proves: "every field name returned is actually printed on the page",
    status: !names
      ? "missing"
      : names.status === "unavailable"
        ? "unavailable"
        : names.passed
          ? "pass"
          : "fail",
    detail: !names
      ? "not run"
      : names.status === "unavailable"
        ? String(names.reason || "no text layer on this page")
        : `${num(names.checked)} name(s) found in the page text`,
    violations: names ? strings(names.violations) : [],
  });

  gates.push({
    id: "grid",
    label: "Grid column",
    proves: "each field sits under the bit column the page prints it in",
    status: !grid
      ? "missing"
      : grid.status === "unavailable"
        ? "unavailable"
        : grid.passed
          ? "pass"
          : "fail",
    detail: !grid
      ? "not run"
      : grid.status === "unavailable"
        ? String(grid.reason || "grid could not be reconstructed")
        : "every field under its printed column",
    violations: grid ? strings(grid.violations) : [],
  });

  gates.push({
    id: "renode",
    label: "Renode execution",
    proves: "the generated driver runs and its MMIO trace matches",
    status: !trace && !verdict ? "missing" : verdict?.passed ? "pass" : "fail",
    detail:
      !trace && !verdict
        ? "needs the Modal container; never executed"
        : String(verdict?.reason || "trace recorded"),
    violations: [],
  });

  return gates;
}

export async function loadSummary(
  chip: string,
  events: RunEvent[],
): Promise<RunSummary> {
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

/** Artifacts discovered from the fixture directory.
 *
 *  Was a hardcoded list of four `usart1_*` names, so `gpio8` (portb_hal.c)
 *  and `pmic32` (pmic_hal.c) rendered an empty code pane, and the Rust HAL,
 *  platform.repl and run_test.resc never appeared for anyone. */
const CODE_EXTENSIONS = [".c", ".h", ".rs", ".svd", ".py", ".repl", ".resc"];

export async function loadArtifacts(
  chip: string,
): Promise<Record<string, string>> {
  const dir = path.join(FIXTURES, chip);
  let names: string[];
  try {
    names = (await readdir(dir, { withFileTypes: true }))
      .filter((d) => d.isFile())
      .map((d) => d.name)
      .filter((n) => CODE_EXTENSIONS.some((ext) => n.endsWith(ext)))
      .sort(byKind);
  } catch {
    return {};
  }

  const out: Record<string, string> = {};
  for (const name of names) {
    try {
      out[name] = await readFile(path.join(dir, name), "utf8");
    } catch {
      // A file listed but unreadable is skipped rather than shown empty.
    }
  }
  return out;
}

/** Header before source, C before Rust, model after the drivers. Stable so
 *  the first tab is always the one worth reading first. */
function byKind(a: string, b: string): number {
  const rank = (n: string) =>
    n.endsWith(".h") ? 0
    : n.endsWith(".c") ? 1
    : n.endsWith(".rs") ? 2
    : n.endsWith(".svd") ? 3
    : n.endsWith(".py") ? 4
    : 5;
  return rank(a) - rank(b) || a.localeCompare(b);
}
