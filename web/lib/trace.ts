/**
 * Parsing the bus trace the simulated chip prints.
 *
 * Pure, and deliberately not in lib/fixtures.ts: the player parses the trace
 * in the browser as the run plays, and importing it from the module that
 * reads the filesystem would pull node:fs into the client bundle.
 */
import type { MmioTransaction } from "./types";

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
