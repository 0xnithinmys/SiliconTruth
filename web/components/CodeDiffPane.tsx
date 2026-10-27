"use client";

import { useState } from "react";

/**
 * The centre pane. Tabs over the generated artifacts, plus the naive-vs-
 * SiliconTruth comparison, which is the demo's money shot (F16) and therefore
 * ranks above the commentary stream if time runs short.
 */
export default function CodeDiffPane({
  artifacts,
}: {
  artifacts: Record<string, string>;
}) {
  const names = Object.keys(artifacts);
  const [active, setActive] = useState(names[0] ?? "");

  if (names.length === 0) {
    return <div className="p-4 text-sm text-neutral-500">no artifacts recorded</div>;
  }

  const body = artifacts[active] ?? "";
  const errataLines = new Set(
    body.split("\n").flatMap((l, i) => (l.includes("ERRATUM") ? [i] : [])),
  );

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 gap-1 overflow-x-auto border-b border-neutral-800 px-2 pt-2">
        {names.map((n) => (
          <button
            key={n}
            onClick={() => setActive(n)}
            className={`whitespace-nowrap rounded-t px-3 py-1.5 font-mono text-xs ${
              n === active
                ? "bg-neutral-900 text-neutral-100"
                : "text-neutral-500 hover:text-neutral-300"
            }`}
          >
            {n}
          </button>
        ))}
      </div>
      <pre className="flex-1 overflow-auto bg-neutral-900 p-3 font-mono text-xs leading-relaxed">
        {body.split("\n").map((line, i) => (
          <div
            key={i}
            className={
              errataLines.has(i)
                ? "bg-amber-500/10 text-amber-200"
                : line.trimStart().startsWith("*") || line.trimStart().startsWith("/*")
                  ? "text-neutral-500"
                  : "text-neutral-300"
            }
          >
            <span className="mr-3 select-none text-neutral-700">
              {String(i + 1).padStart(3)}
            </span>
            {line || " "}
          </div>
        ))}
      </pre>
    </div>
  );
}
