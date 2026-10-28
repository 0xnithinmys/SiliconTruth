"use client";

import { useState } from "react";

import type { PageIndex, PageRegion } from "@/lib/pages";

/**
 * The page a value was actually read from, with the region highlighted.
 *
 * Shows the EXACT raster the model was shown, not a re-render. That is the
 * whole point of the pane: a highlight that lines up here is evidence the
 * region lined up for the model too. A pdf.js canvas would re-rasterise at
 * some other resolution, so the alignment it displays would prove nothing
 * about the read.
 *
 * Boxes arrive in the recorded image's pixel space, so they are scaled by
 * one factor -- the rendered width over the recorded width -- and expressed
 * as percentages, which keeps them aligned at any viewport size without a
 * resize listener.
 */
export default function PagePane({
  index,
  selected,
  onSelect,
}: {
  index: PageIndex;
  selected?: string | null;
  onSelect?: (register: string) => void;
}) {
  const [pageIdx, setPageIdx] = useState(0);
  const [hover, setHover] = useState<string | null>(null);

  const page = index.pages[Math.min(pageIdx, index.pages.length - 1)];
  if (!page) return null;

  const wholePage = page.regions.filter((r) => r.whole_page);
  const located = page.regions.filter((r) => !r.whole_page);

  const pct = (r: PageRegion) => {
    const [x0, y0, x1, y1] = r.bbox;
    return {
      left: `${(x0 / page.width) * 100}%`,
      top: `${(y0 / page.height) * 100}%`,
      width: `${((x1 - x0) / page.width) * 100}%`,
      height: `${((y1 - y0) / page.height) * 100}%`,
    };
  };

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-4">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-neutral-400">
            Source page
          </h3>
          <p className="mt-0.5 font-mono text-xs text-neutral-300">
            page {page.page} &middot; {page.width}&times;{page.height}px @ {index.dpi} DPI
          </p>
        </div>
        {index.pages.length > 1 && (
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setPageIdx((i) => Math.max(0, i - 1))}
              disabled={pageIdx === 0}
              className="rounded border border-neutral-700 px-2 py-1 text-xs text-neutral-300 disabled:opacity-40"
              aria-label="Previous page"
            >
              &larr;
            </button>
            <span className="px-1 font-mono text-xs text-neutral-400">
              {pageIdx + 1}/{index.pages.length}
            </span>
            <button
              type="button"
              onClick={() =>
                setPageIdx((i) => Math.min(index.pages.length - 1, i + 1))
              }
              disabled={pageIdx === index.pages.length - 1}
              className="rounded border border-neutral-700 px-2 py-1 text-xs text-neutral-300 disabled:opacity-40"
              aria-label="Next page"
            >
              &rarr;
            </button>
          </div>
        )}
      </div>

      <div className="relative w-full overflow-hidden rounded-lg border border-neutral-700 bg-white">
        {/* eslint-disable-next-line @next/next/no-img-element -- the recorded
            raster must not be re-encoded or resized by the image optimiser:
            it is the exact pixels the model was shown. */}
        <img
          src={`/fixtures/${index.chip}/${page.image}`}
          alt={`${index.chip} datasheet page ${page.page}`}
          width={page.width}
          height={page.height}
          className="block h-auto w-full"
        />

        {page.regions.filter((r) => !r.whole_page).map((r) => {
          const active = selected === r.register || hover === r.register;
          return (
            <button
              key={`${r.register}-${r.bbox.join(",")}`}
              type="button"
              style={pct(r)}
              onMouseEnter={() => setHover(r.register)}
              onMouseLeave={() => setHover(null)}
              onClick={() => onSelect?.(r.register)}
              title={`${r.register} — ${r.fields} fields — ${
                r.verified ? "verified" : "UNVERIFIED"
              }`}
              aria-label={`Select register ${r.register}`}
              className={[
                "absolute cursor-pointer border-2 transition-colors",
                active
                  ? "border-emerald-400 bg-emerald-400/20"
                  : r.verified
                    ? "border-emerald-500/60 bg-emerald-500/5 hover:bg-emerald-400/15"
                    : "border-amber-500/70 bg-amber-500/10 hover:bg-amber-400/20",
              ].join(" ")}
            >
              <span className="absolute -top-px left-0 translate-y-[-100%] whitespace-nowrap rounded-t bg-neutral-900/90 px-1 font-mono text-[10px] text-neutral-100">
                {r.register}
                {!r.verified && " · UNVERIFIED"}
              </span>
            </button>
          );
        })}
      </div>

      {wholePage.length > 0 && (
        <p className="rounded-lg bg-neutral-800/60 p-2 text-xs leading-relaxed text-neutral-300">
          <span className="font-mono text-neutral-100">
            {wholePage.map((r) => r.register).join(", ")}
          </span>{" "}
          {wholePage.length === 1 ? "was" : "were"} read from the{" "}
          <strong className="text-neutral-100">whole page</strong>, not a
          located region. Nothing is outlined because nothing was localised
          &mdash; drawing a border around everything would claim otherwise.
          Run <span className="font-mono">extract --segment</span> to locate
          tables first.
        </p>
      )}

      {located.length === 0 && wholePage.length === 0 ? (
        <p className="text-xs leading-relaxed text-neutral-400">
          No regions recorded for this page. The page is shown as captured;
          nothing is highlighted because nothing claimed to have been read
          from it.
        </p>
      ) : located.length === 0 ? null : (
        <p className="text-xs leading-relaxed text-neutral-400">
          Each box is where a register was actually read from. The
          coordinates come from the IR&apos;s provenance, which is filled in
          Python from crop metadata &mdash; never reported by the model
          &mdash; so this shows where we looked, not where something claimed
          to have looked. Click a box to select that register.
        </p>
      )}
    </div>
  );
}
