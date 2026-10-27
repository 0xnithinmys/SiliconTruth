/**
 * Fixture loading for replay mode. Runs on the SERVER at build time, so the
 * replay routes prerender and a judge hits a CDN edge cache: no API calls,
 * no cold start, no key.
 */
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

import type { FixtureIndex, MmioTransaction, RunEvent, Z3Audit } from "./types";

const FIXTURES = path.join(process.cwd(), "public", "fixtures");

export async function loadIndex(): Promise<FixtureIndex> {
  try {
    const raw = await readFile(path.join(FIXTURES, "index.json"), "utf8");
    return JSON.parse(raw) as FixtureIndex;
  } catch {
    // No fixtures recorded yet. An empty list renders an honest empty state
    // rather than a crash.
    return { schema: 1, chips: [] };
  }
}

export async function listChips(): Promise<string[]> {
  try {
    const entries = await readdir(FIXTURES, { withFileTypes: true });
    return entries.filter((e) => e.isDirectory()).map((e) => e.name);
  } catch {
    return [];
  }
}

export async function loadRun(chip: string): Promise<RunEvent[]> {
  try {
    const raw = await readFile(path.join(FIXTURES, chip, "run.jsonl"), "utf8");
    return raw
      .split("\n")
      .filter((l) => l.trim())
      .flatMap((l) => {
        try {
          return [JSON.parse(l) as RunEvent];
        } catch {
          // A partial trace from a crashed run is still worth showing.
          return [];
        }
      });
  } catch {
    return [];
  }
}

export async function loadArtifact(chip: string, name: string): Promise<string | null> {
  try {
    return await readFile(path.join(FIXTURES, chip, name), "utf8");
  } catch {
    return null;
  }
}

/** Pull the Z3 verdict out of a recorded run. */
export function z3From(events: RunEvent[]): Z3Audit | null {
  const e = events.find((x) => x.kind === "z3_audit");
  if (!e) return null;
  return {
    passed: Boolean(e.passed),
    elapsed_ms: Number(e.elapsed_ms ?? 0),
    registers: Number(e.registers ?? 0),
    violations: (e.violations as string[]) ?? [],
  };
}

/** Parse the MMIO lines the generated peripheral prints.
 *  Mirrors MMIO_LINE in silicontruth/oracle/renode_oracle.py. */
const MMIO = /SILICONTRUTH_MMIO[ \t]+(READ|WRITE)[ \t]+0x([0-9A-Fa-f]+)[ \t]+(\S+)[ \t]+0x([0-9A-Fa-f]+)[ \t]+\[(PASS|FAIL)\](?:[ \t]+(\S+))?/g;

export function parseTrace(text: string): MmioTransaction[] {
  const out: MmioTransaction[] = [];
  for (const m of text.matchAll(MMIO)) {
    out.push({
      kind: m[1] as "READ" | "WRITE",
      offset: parseInt(m[2], 16),
      register: m[3],
      value: parseInt(m[4], 16),
      verdict: m[5] as "PASS" | "FAIL",
      note: m[6],
    });
  }
  return out;
}

export function hex(n: number, width = 8): string {
  return "0x" + n.toString(16).toUpperCase().padStart(width, "0");
}
