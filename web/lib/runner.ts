/**
 * Driving a real pipeline run from an uploaded PDF.
 *
 * SERVER ONLY. This spawns a process and touches the filesystem; none of it
 * may ever reach the browser bundle.
 *
 * The design decision worth stating: this does NOT reimplement the pipeline
 * in TypeScript. It shells out to `silicontruth pipeline`, which is the same
 * code path the CLI runs, and then serves the JSONL that the Python recorder
 * writes. The event format therefore has exactly one definition, on the
 * Python side, and the live view and the recorded replays are reading the
 * same thing. A second implementation here would drift the first time
 * anybody touched the recorder.
 *
 * Deliberate limitation, stated rather than hidden: run state lives in a
 * module-level Map in this process. That is fine for a self-hosted server
 * (`next start`) and wrong for a serverless deployment, where each request
 * may land in a different instance. It is not a gap worth closing with a
 * database, because the thing this spawns needs Docker and a local
 * filesystem, so it cannot run serverless either way. The replay routes stay
 * static and keyless regardless; this is the opt-in live half.
 */
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdir, mkdtemp, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import type { RunEvent } from "./types";

/** The repo root, one level up from the Next app. */
const REPO = path.resolve(process.cwd(), "..");
const PYTHON = process.env.SILICONTRUTH_PYTHON ?? "python";

const CODE_EXTENSIONS = [".c", ".h", ".rs", ".svd", ".py", ".repl", ".resc"];

export type RunStatus = "running" | "passed" | "failed";

export interface RunRequest {
  chip: string;
  peripheral: string;
  /** Parsed base address. Never asked of the model, so never guessed here. */
  base: number;
  pages: number[];
  errataPage: number;
  pdf: { name: string; bytes: Buffer };
  errata?: { name: string; bytes: Buffer };
  skipEmulate: boolean;
}

interface Job {
  id: string;
  chip: string;
  dir: string;
  status: RunStatus;
  startedAt: number;
  endedAt?: number;
  exitCode: number | null;
  /** Kept so a failure can show what the pipeline actually said. A run that
   *  fails with a blank reason is the thing this whole project is against. */
  log: string[];
  stage: string;
}

const jobs = new Map<string, Job>();

/** Only the stage banners `cmd_pipeline` prints, so the UI can say which
 *  stage is in flight before any event for it has been recorded. */
const STAGE_RE = /^-- (extract|build|emulate)( skipped)? --$/;

/** Provider key names, mirroring `_PROVIDERS[*]["key_var"]` in
 *  silicontruth/models/provider.py. Any one of them is enough to read a PDF. */
const KEY_VARS = [
  "MODEL_API_KEY",
  "OPENROUTER_API_KEY",
  "GROQ_API_KEY",
  "TOGETHER_API_KEY",
];

/**
 * Whether a run could actually read a PDF — answered from the same place the
 * Python side answers it.
 *
 * This deliberately looks at the repo-root `.env`, not just `process.env`.
 * Next only loads `.env` files from the app directory (`web/`), and the key
 * lives one level up where `provider.load_env()` reads it. Checking only
 * Next's own environment reported live mode as unavailable on a machine where
 * it works perfectly well, because the subprocess inherits nothing from Next
 * and reads that file itself.
 *
 * Returns booleans only. The key is never part of the result, and nothing
 * here is exposed to the client beyond these flags.
 */
export function describeCapabilities(): {
  live_available: boolean;
  has_key: boolean;
  reason?: string;
} {
  const hasKey =
    KEY_VARS.some((v) => Boolean(process.env[v])) || repoEnvHasKey();
  return {
    live_available: hasKey,
    has_key: hasKey,
    // Said in words a user can act on, and the same sentence `doctor` uses.
    reason: hasKey
      ? undefined
      : "No inference provider is configured on the server, so reading a PDF " +
        "is not available. Set MODEL_API_KEY in the repository's .env file. " +
        "The recorded runs need no key and work regardless.",
  };
}

/** Cached: this reads the disk, and the capability probe is polled. */
let repoEnvKey: boolean | null = null;

function repoEnvHasKey(): boolean {
  if (repoEnvKey !== null) return repoEnvKey;
  try {
    // Sync on purpose: describeCapabilities is called from a synchronous
    // server component, and this runs once per process.
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { readFileSync } = require("node:fs") as typeof import("node:fs");
    const text = readFileSync(path.join(REPO, ".env"), "utf8");
    repoEnvKey = text.split("\n").some((line) => {
      const t = line.trim();
      if (!t || t.startsWith("#")) return false;
      const eq = t.indexOf("=");
      if (eq < 0) return false;
      // A var present but empty is not a key.
      return KEY_VARS.includes(t.slice(0, eq).trim()) && t.slice(eq + 1).trim() !== "";
    });
  } catch {
    repoEnvKey = false;
  }
  return repoEnvKey;
}

/**
 * How many pages a PDF has, answered by the same library that will render
 * them.
 *
 * The form asked for pages before knowing whether the document had them, so
 * "412 413" against a 2-page upload started a run, called an inference
 * provider, and failed partway through with a Python traceback in the
 * browser. Checking first turns that into a field error before anything
 * runs.
 */
export async function pdfPageCount(bytes: Buffer): Promise<number | null> {
  const dir = await mkdtemp(path.join(tmpdir(), "silicontruth-probe-"));
  const file = path.join(dir, "probe.pdf");
  await writeFile(file, bytes);
  try {
    const out = await new Promise<string>((resolve, reject) => {
      const child = spawn(PYTHON, ["-m", "silicontruth.cli", "probe", file], {
        cwd: REPO,
      });
      let buf = "";
      child.stdout.on("data", (d) => (buf += d.toString()));
      child.on("error", reject);
      child.on("close", (code) =>
        code === 0 ? resolve(buf) : reject(new Error(`probe exited ${code}`)),
      );
    });
    const n = JSON.parse(out).pages;
    return Number.isInteger(n) ? n : null;
  } catch (e) {
    // Unreadable here is not necessarily unreadable later, and refusing an
    // upload because the probe failed would be worse than letting the run
    // report the real reason. Skip the check -- but SAY SO on the server,
    // because a validation that quietly stops running is indistinguishable
    // from one that passes, and this project exists to object to that.
    console.error("[runner] page-count probe failed, skipping the check:", e);
    return null;
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

export async function startRun(req: RunRequest): Promise<string> {
  const id = randomUUID();
  const dir = await mkdtemp(path.join(tmpdir(), `silicontruth-${id.slice(0, 8)}-`));
  const inputs = path.join(dir, "inputs");
  await mkdir(inputs, { recursive: true });

  const pdfPath = path.join(inputs, "manual.pdf");
  await writeFile(pdfPath, req.pdf.bytes);

  let errataPath: string | undefined;
  if (req.errata) {
    errataPath = path.join(inputs, "errata.pdf");
    await writeFile(errataPath, req.errata.bytes);
  }

  const args = [
    "-m", "silicontruth.cli", "pipeline", pdfPath,
    "--pages", ...req.pages.map(String),
    "--chip", req.chip,
    "--peripheral", req.peripheral,
    // Hex, because --base parses with int(x, 0) and a decimal string for an
    // MMIO base is unreadable in a log.
    "--base", `0x${req.base.toString(16)}`,
    "--fixtures", path.join(dir, "fixtures"),
    "-o", path.join(dir, "out"),
  ];
  if (errataPath) args.push("--errata", errataPath, "--errata-page", String(req.errataPage));
  if (req.skipEmulate) args.push("--skip-emulate");

  const job: Job = {
    id, chip: req.chip, dir, status: "running", startedAt: Date.now(),
    exitCode: null, log: [], stage: "extract",
  };
  jobs.set(id, job);

  const child = spawn(PYTHON, args, {
    cwd: REPO,
    // Unbuffered, or Python holds the stage banners until exit and the UI
    // shows "extract" for the entire run.
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
  });

  const absorb = (buf: Buffer) => {
    for (const raw of buf.toString().split("\n")) {
      // The CLI colours its output; the codes are noise in a browser.
      const line = raw.replace(/\u001b\[[0-9;]*m/g, "").trimEnd();
      if (!line.trim()) continue;
      job.log.push(line);
      const m = STAGE_RE.exec(line.trim());
      if (m) job.stage = m[1];
    }
    // A runaway log must not become a memory leak.
    if (job.log.length > 2000) job.log.splice(0, job.log.length - 2000);
  };
  child.stdout.on("data", absorb);
  child.stderr.on("data", absorb);

  child.on("error", (e) => {
    job.log.push(`failed to start ${PYTHON}: ${e.message}`);
    job.status = "failed";
    job.exitCode = -1;
    job.endedAt = Date.now();
  });
  child.on("close", (code) => {
    job.exitCode = code;
    job.status = code === 0 ? "passed" : "failed";
    job.endedAt = Date.now();
  });

  return id;
}

export interface RunSnapshot {
  id: string;
  chip: string;
  status: RunStatus;
  stage: string;
  exitCode: number | null;
  events: RunEvent[];
  artifacts: Record<string, string>;
  log: string[];
  /** The one sentence worth reading, pulled out of the log.
   *
   *  The pane used to print the whole tail, so a bad page number arrived as
   *  forty frames of Python with the real reason buried in the middle. The
   *  CLI now prints `error <message>` for anything caused by the input, so
   *  that line is the headline and the log stays underneath as detail. */
  reason: string | null;
  elapsedMs: number;
}

export async function getRun(id: string): Promise<RunSnapshot | null> {
  const job = jobs.get(id);
  if (!job) return null;

  const runDir = path.join(job.dir, "fixtures", job.chip);
  return {
    id: job.id,
    chip: job.chip,
    status: job.status,
    stage: job.stage,
    exitCode: job.exitCode,
    events: await readEvents(path.join(runDir, "run.jsonl")),
    artifacts: await readArtifacts(runDir),
    // Only the tail. The whole log is for the server's own debugging.
    log: job.log.slice(-40),
    reason: failureReason(job.log),
    elapsedMs: (job.endedAt ?? Date.now()) - job.startedAt,
  };
}

/** The `error ...` line the CLI prints for bad input, else the last line
 *  that is not Python stack furniture. */
function failureReason(log: string[]): string | null {
  const tagged = log.find((l) => /^error\s/i.test(l.trim()));
  if (tagged) return tagged.trim().replace(/^error\s+/i, "");
  const noise = /^(Traceback|  File \"|    |\^+$|During handling|The above)/;
  const tail = [...log].reverse().find((l) => l.trim() && !noise.test(l));
  return tail ? tail.trim() : null;
}

async function readEvents(file: string): Promise<RunEvent[]> {
  let raw: string;
  try {
    raw = await readFile(file, "utf8");
  } catch {
    // Nothing recorded yet. An empty list is the honest answer during the
    // seconds before the first event lands.
    return [];
  }
  return raw
    .split("\n")
    .filter((l) => l.trim())
    .flatMap((l) => {
      try {
        return [JSON.parse(l) as RunEvent];
      } catch {
        // The recorder appends line by line, so polling mid-write can catch a
        // half-written line. Skipping it shows one event late instead of
        // failing the whole poll.
        return [];
      }
    });
}

async function readArtifacts(dir: string): Promise<Record<string, string>> {
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
      // Mid-write. It will be there on the next poll.
    }
  }
  return out;
}

/** Same order as lib/pipeline.ts: header, source, Rust, map, model. */
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
