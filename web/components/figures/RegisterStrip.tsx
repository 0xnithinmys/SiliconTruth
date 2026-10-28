"use client";

import { useState } from "react";

import { type BitMap, isReserved, slotsOf } from "@/lib/bitfields";

/**
 * A register drawn as the 32 bits it actually is.
 *
 * This is the figure the project was missing: twenty settings packed into one
 * 32-bit address, every boundary read off a table in a PDF, was a list of hex
 * masks and nothing else.
 *
 * Drawn from the generated SVD, so it shows verified output rather than what
 * the model claimed. It does NOT re-derive gate 1: width conservation counts
 * declared reserved fields, which the SVD deliberately omits, so a hole here
 * means reserved and never a failure. See lib/bitfields.ts.
 *
 * FLEXBOX, NOT A SCALED SVG. The first version was an SVG with a 0..100
 * viewBox and preserveAspectRatio="none", which has two faults that only show
 * once it is wide: the height scales with the width, so a wider column made a
 * bit strip 280px tall, and the x and y scales diverge, so every field label
 * stretched horizontally. Flex grow on a bit count gives exact proportional
 * widths at a fixed height, and the labels are real text.
 *
 * Encoding, in the order the method puts it:
 *  - FORM. The x-axis is bit position, msb-left as a reference manual prints
 *    it; segment width is the field's bit count, so a 6-bit field is visibly
 *    six times a 1-bit flag.
 *  - COLOR. One hue for declared fields, deliberately desaturated for
 *    reserved, which should read as absent. Status colors stay reserved for
 *    state and never decorate a field.
 *  - NOT COLOR ALONE. Reserved carries a hatch, an overlap a different hatch
 *    plus an icon and a count. Red and green are 4.1 ΔE apart under
 *    deuteranopia, so hue alone would hide the one real failure.
 *  - SPACERS. A 2px surface gap between neighbouring fills, so adjacent
 *    fields separate without needing a second hue.
 */

const FIELD = "#2a78d6";
const FIELD_HOVER = "#1b5fb0";

/** Reserved: neutral, hatched, recessive. */
const RESERVED_HATCH =
  "repeating-linear-gradient(45deg, #cbd5e1 0 1px, #f1f5f9 1px 4px)";
/** An overlap cannot be a convention, so it is the one alarming texture. */
const OVERLAP_HATCH =
  "repeating-linear-gradient(45deg, #d03b3b 0 1.5px, #fef2f2 1.5px 5px)";

/** Under this many bits a label cannot fit, so it is not drawn. Every field
 *  stays reachable by hover and in the field list, so nothing depends on it
 *  fitting. */
const LABEL_MIN_BITS = 3;

export default function RegisterStrip({
  map,
  verified = true,
  baseAddress,
  fieldTable = false,
}: {
  map: BitMap;
  verified?: boolean;
  baseAddress?: number | null;
  /** Render every field as a visible list under the strip.
   *
   *  Required relief, not an extra. Only fields of three bits or more can
   *  hold a direct label, so on a register of 1-bit flags the strip names two
   *  of twenty and the rest would be reachable only by hover — no use on a
   *  touch screen, in print, or to someone following the visual order. */
  fieldTable?: boolean;
}) {
  const [hover, setHover] = useState<string | null>(null);

  const bits = map.width || 32;
  const slots = slotsOf(map);
  const broken = map.overlapping.length > 0;
  const reservedBits = map.undeclared.length;
  const named = map.fields.filter((f) => !isReserved(f.name));

  return (
    <figure className="w-full">
      <figcaption className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-mono text-sm font-semibold text-slate-900">
          {map.register}
        </span>
        <span className="font-mono text-xs text-slate-500 tabular">
          {baseAddress != null
            ? `0x${(baseAddress + map.offset).toString(16).toUpperCase()}`
            : `+0x${map.offset.toString(16).toUpperCase().padStart(2, "0")}`}
        </span>
        <span className="text-xs text-slate-500">
          {named.length} fields, {bits}-bit
          {reservedBits > 0 ? `, ${reservedBits} reserved` : ""}
        </span>
        {broken ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700 ring-1 ring-red-200">
            {/* Icon + words, never the colour alone. */}
            <Warn />
            {map.overlapping.length} bit
            {map.overlapping.length === 1 ? "" : "s"} claimed by two fields
          </span>
        ) : !verified ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800 ring-1 ring-amber-200">
            <Warn />
            Rejected by a check, not generated
          </span>
        ) : null}
      </figcaption>

      {/* The strip: one row of proportional segments at a fixed height. */}
      <div
        className="flex h-8 w-full gap-[2px] overflow-hidden rounded-md"
        role="img"
        aria-label={`${map.register}: ${named
          .map((f) =>
            f.msb === f.lsb
              ? `${f.name} bit ${f.msb}`
              : `${f.name} bits ${f.msb} to ${f.lsb}`,
          )
          .join(", ")}${
          reservedBits > 0 ? `. Reserved bits: ${map.undeclared.join(", ")}` : ""
        }${
          broken
            ? `. INVALID, bits claimed twice: ${map.overlapping.join(", ")}`
            : ""
        }`}
      >
        {slots.map((slot) => {
          const active = slot.name !== null && hover === slot.name;
          const isField =
            slot.kind === "field" && !isReserved(slot.name ?? "");
          const range =
            slot.msb === slot.lsb ? `${slot.msb}` : `${slot.msb}:${slot.lsb}`;
          return (
            <div
              key={`${slot.kind}-${slot.msb}-${slot.name ?? ""}`}
              // flex-grow carries the bit count with a zero basis, so widths
              // stay exactly proportional at any container width.
              style={{
                flexGrow: slot.width,
                flexBasis: 0,
                background:
                  slot.kind === "overlap"
                    ? OVERLAP_HATCH
                    : isField
                      ? verified
                        ? active
                          ? FIELD_HOVER
                          : FIELD
                        : "#d03b3b"
                      : RESERVED_HATCH,
              }}
              className="flex min-w-0 items-center justify-center transition-colors"
              onMouseEnter={() => slot.name && setHover(slot.name)}
              onMouseLeave={() => setHover(null)}
              title={slot.name ? `${slot.name} [${range}]` : `reserved [${range}]`}
            >
              {isField && slot.width >= LABEL_MIN_BITS && (
                <span className="truncate px-1 font-mono text-[10px] leading-none text-white">
                  {slot.name}
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* Bit ruler. One cell per bit so the numbers line up with the segments
          above; only every fourth is printed, because a tick per bit is noise
          at this width. */}
      <div className="mt-1 flex w-full gap-[2px]" aria-hidden="true">
        {Array.from({ length: bits }, (_, i) => bits - 1 - i).map((b) => (
          <div
            key={`tick-${b}`}
            style={{ flexGrow: 1, flexBasis: 0 }}
            className="min-w-0 text-center font-mono text-[9px] leading-none text-slate-400 tabular"
          >
            {b % 4 === 0 || b === bits - 1 ? b : ""}
          </div>
        ))}
      </div>

      {fieldTable && (
        <ul className="mt-3 flex flex-wrap gap-1.5">
          {named.map((f) => {
            const active = hover === f.name;
            return (
              <li key={`tbl-${f.name}-${f.lsb}`}>
                <button
                  type="button"
                  onMouseEnter={() => setHover(f.name)}
                  onMouseLeave={() => setHover(null)}
                  onFocus={() => setHover(f.name)}
                  onBlur={() => setHover(null)}
                  className={[
                    "cursor-default rounded-md border px-1.5 py-0.5 font-mono text-[11px] transition-colors tabular",
                    active
                      ? "border-[#2a78d6] bg-[#2a78d6]/10 text-[#1b5fb0]"
                      : "border-slate-200 bg-white text-slate-600 hover:border-slate-300",
                  ].join(" ")}
                >
                  {f.name}
                  <span className="ml-1 text-slate-400">
                    {f.msb === f.lsb ? f.msb : `${f.msb}:${f.lsb}`}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </figure>
  );
}

/** A wedge, shown wherever a status colour appears, so meaning never rests
 *  on hue alone. */
function Warn() {
  return (
    <svg viewBox="0 0 10 10" className="size-2.5" aria-hidden="true">
      <path d="M5 0.5 L9.5 9 L0.5 9 Z" fill="currentColor" />
    </svg>
  );
}
