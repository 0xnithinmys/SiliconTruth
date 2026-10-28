/**
 * Reading a recorded run and its generated files off disk.
 *
 * Server only: this is the half that touches node:fs. The shapes and the check
 * list live in lib/run.ts, which the client panes import.
 */
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

import { gatesFrom, type ExtractedRegister, type LinkedErratum, type RunSummary } from "./run";
import type { RunEvent } from "./types";

const FIXTURES = path.join(process.cwd(), "public", "fixtures");

function num(v: unknown, fallback = 0): number {
  return typeof v === "number" ? v : fallback;
}

function strings(v: unknown): string[] {
  return Array.isArray(v) ? v.map((x) => String(x)) : [];
}

function last(events: RunEvent[], kind: string): RunEvent | undefined {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].kind === kind) return events[i];
  }
  return undefined;
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
