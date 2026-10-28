/**
 * Fixture loading for replay mode. Runs on the SERVER at build time, so the
 * replay routes prerender and a judge hits a CDN edge cache: no API calls,
 * no cold start, no key.
 */
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

import type { FixtureIndex, RunEvent } from "./types";

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
