// `next build` with a raised heap, because the default one is not enough here.
//
// The build compiled fine and then died in Next's lint-and-typecheck worker
// with "FATAL ERROR: Zone Allocation failed - process out of memory", exit
// 134. It is not a type error: `npx tsc --noEmit -p tsconfig.json` passes
// clean, so the worker is simply running out of room on this project.
//
// A wrapper rather than `NODE_OPTIONS=... next build` in package.json,
// because npm runs scripts through cmd.exe on Windows and the inline
// VAR=value prefix is a POSIX-shell thing that fails there. A wrapper is also
// why this needs no cross-env dependency.
import { spawn } from "node:child_process";

const HEAP_MB = 4096;

const existing = process.env.NODE_OPTIONS ?? "";
// Respect an explicit override from the environment instead of stacking a
// second --max-old-space-size onto it, since the last flag would win silently.
const nodeOptions = existing.includes("--max-old-space-size")
  ? existing
  : `${existing} --max-old-space-size=${HEAP_MB}`.trim();

const child = spawn("next", ["build", ...process.argv.slice(2)], {
  stdio: "inherit",
  shell: true,
  env: { ...process.env, NODE_OPTIONS: nodeOptions },
});

child.on("exit", (code, signal) => {
  if (signal) {
    console.error(`[build] next build terminated by signal ${signal}`);
    process.exit(1);
  }
  process.exit(code ?? 1);
});
