// Copy recorded fixtures into public/ before every build, so the deployed
// replay can never silently go stale against the recorder output.
import { cp, mkdir, access, rm } from "node:fs/promises";
import path from "node:path";

const src = path.resolve(process.cwd(), "..", "fixtures");
const dst = path.resolve(process.cwd(), "public", "fixtures");

try {
  await access(src);
} catch {
  console.warn(`[prebuild] no fixtures at ${src}; replay will render an empty state`);
  await mkdir(dst, { recursive: true });
  process.exit(0);
}

// Clear first. cp() merges, so a fixture deleted from the repo lingered in
// public/ forever and kept showing up in the deployed demo as a run you
// could open. One of them (final_check) was doing exactly that.
await rm(dst, { recursive: true, force: true });
await mkdir(path.dirname(dst), { recursive: true });
await cp(src, dst, { recursive: true });
console.log(`[prebuild] fixtures -> public/fixtures`);
