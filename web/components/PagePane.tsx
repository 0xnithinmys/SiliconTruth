"use client";

import { ChevronLeft, ChevronRight, Maximize2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
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
 * one factor, the rendered width over the recorded width, and expressed as
 * percentages. That keeps them aligned at any viewport size with no resize
 * listener.
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
    <ScrollArea className="h-full">
      <div className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold">The page it read</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              This is the exact image the model was shown, straight from the
              PDF. Page {page.page}.
            </p>
          </div>
          {index.pages.length > 1 && (
            <div className="flex shrink-0 items-center gap-1">
              <Button
                size="icon"
                variant="outline"
                onClick={() => setPageIdx((i) => Math.max(0, i - 1))}
                disabled={pageIdx === 0}
                aria-label="Previous page"
              >
                <ChevronLeft />
              </Button>
              <span className="px-1 font-mono text-xs text-muted-foreground">
                {pageIdx + 1}/{index.pages.length}
              </span>
              <Button
                size="icon"
                variant="outline"
                onClick={() =>
                  setPageIdx((i) => Math.min(index.pages.length - 1, i + 1))
                }
                disabled={pageIdx === index.pages.length - 1}
                aria-label="Next page"
              >
                <ChevronRight />
              </Button>
            </div>
          )}
        </div>

        <div className="relative w-full overflow-hidden rounded-lg border bg-white">
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

          {located.map((r) => {
            const active = selected === r.register || hover === r.register;
            return (
              <button
                key={`${r.register}-${r.bbox.join(",")}`}
                type="button"
                style={pct(r)}
                onMouseEnter={() => setHover(r.register)}
                onMouseLeave={() => setHover(null)}
                onClick={() => onSelect?.(r.register)}
                title={`${r.register}, ${r.fields} settings, ${
                  r.verified ? "checks passed" : "rejected by a check"
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
                  {!r.verified && ", rejected"}
                </span>
              </button>
            );
          })}
        </div>

        {/* A datasheet page shrunk into a side column is unreadable, which
            defeats the one thing this pane is for. The full-size raster is a
            click away, still the recorded pixels and still with the boxes on
            it. */}
        <Dialog>
          <DialogTrigger asChild>
            <Button variant="outline" size="sm" className="w-full">
              <Maximize2 /> See the full page
            </Button>
          </DialogTrigger>
          <DialogContent className="max-h-[92vh] overflow-auto p-2 sm:max-w-4xl">
            <DialogTitle className="sr-only">
              {index.chip} page {page.page}, full size
            </DialogTitle>
            <div className="relative bg-white">
              {/* eslint-disable-next-line @next/next/no-img-element -- same
                  recorded raster, unprocessed. */}
              <img
                src={`/fixtures/${index.chip}/${page.image}`}
                alt={`${index.chip} datasheet page ${page.page}`}
                width={page.width}
                height={page.height}
                className="block h-auto w-full"
              />
              {located.map((r) => (
                <span
                  key={`zoom-${r.register}-${r.bbox.join(",")}`}
                  style={pct(r)}
                  className="absolute border-2 border-emerald-500/70 bg-emerald-400/10"
                />
              ))}
            </div>
          </DialogContent>
        </Dialog>

        {located.length > 0 && (
          <p className="text-sm text-muted-foreground">
            Each box is where one register was read from. Click one to follow it
            into the code and the checks.
          </p>
        )}

        {wholePage.length > 0 && (
          <p className="text-sm text-muted-foreground">
            <span className="font-mono text-foreground">
              {wholePage.map((r) => r.register).join(", ")}
            </span>{" "}
            {wholePage.length === 1 ? "was" : "were"} read from the whole page
            rather than a located table, so there is nothing to outline.
          </p>
        )}

        {located.length === 0 && wholePage.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Nothing is highlighted on this page, because nothing in the output
            claims to have been read from it.
          </p>
        )}
      </div>
    </ScrollArea>
  );
}
