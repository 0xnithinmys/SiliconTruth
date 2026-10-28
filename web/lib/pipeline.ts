/**
 * Reading a recorded run and its generated files off disk.
 *
 * Server only: this is the half that touches node:fs. The shapes, the check
 * list and summarize() live in lib/run.ts, because the player rebuilds the
 * summary on the client as the run plays.
 */
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

const FIXTURES = path.join(process.cwd(), "public", "fixtures");

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
