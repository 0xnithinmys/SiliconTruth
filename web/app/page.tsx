import Link from "next/link";

import { loadIndex } from "@/lib/fixtures";

/**
 * T-133 — the landing page defaults to replay. A judge with ninety seconds and
 * no patience must see a working demo immediately: no key, no signup, no
 * backend, no cold start.
 */
export default async function Home() {
  const index = await loadIndex();

  return (
    <div className="mx-auto max-w-3xl px-4 py-12">
      <h1 className="text-2xl font-semibold tracking-tight">
        A chip that boots, and a proof of every bit that made it boot.
      </h1>
      <p className="mt-3 leading-relaxed text-neutral-400">
        SiliconTruth reads a datasheet and its silicon errata sheet and emits a
        verified hardware support package: a CMSIS-SVD register map, a C/Rust HAL
        with errata workarounds injected, and a Renode virtual peripheral. Every
        offset is proved by a Z3 SMT solver before any code is generated, and
        every driver is executed in emulation before it is called correct.
      </p>

      <h2 className="mt-10 text-xs font-semibold uppercase tracking-wider text-neutral-400">
        Recorded runs
      </h2>

      {index.chips.length === 0 ? (
        <p className="mt-3 rounded-lg border border-dashed border-neutral-700 p-4 text-sm text-neutral-400">
          No runs recorded yet. Run{" "}
          <code className="font-mono text-neutral-300">
            silicontruth build &lt;ir.json&gt;
          </code>{" "}
          and copy <code className="font-mono text-neutral-300">fixtures/</code> into{" "}
          <code className="font-mono text-neutral-300">web/public/fixtures/</code>.
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-neutral-800 rounded-lg border border-neutral-800">
          {index.chips.map((c) => (
            <li key={c.chip}>
              <Link
                href={`/replay/${c.chip}`}
                className="flex items-center justify-between px-4 py-3 hover:bg-neutral-900"
              >
                <span className="font-mono text-sm">{c.chip}</span>
                <span className="flex items-center gap-3 text-xs text-neutral-500">
                  <span>{c.peripheral}</span>
                  <span>{c.events} events</span>
                  <span>{c.duration_ms.toFixed(0)}ms</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      <p className="mt-8 text-xs leading-relaxed text-neutral-500">
        Replay reads static JSON recorded from real pipeline runs. Open the network
        tab: there are no API calls.
      </p>
    </div>
  );
}
