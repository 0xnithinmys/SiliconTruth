// Copy recorded fixtures into public/ before every build, so the deployed
// replay can never silently go stale against the recorder output.
import { cp, mkdir, access } from "node:fs/promises";
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

await mkdir(path.dirname(dst), { recursive: true });
await cp(src, dst, { recursive: true });
console.log(`[prebuild] fixtures -> public/fixtures`);
