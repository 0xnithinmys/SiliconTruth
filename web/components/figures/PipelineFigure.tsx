import { PIPELINE_STAGES, type PipelineStage } from "@/lib/wording";

/**
 * The two gates, drawn.
 *
 * The architecture is the argument this project makes, and until now the
 * README had an ASCII diagram of it while the landing page had three prose
 * cards. This is that diagram, as a figure: six stages, with the two that are
 * GATES marked as gates and a visible reject lane leaving the first one.
 *
 * HTML and CSS rather than one wide SVG on purpose. A six-stage horizontal
 * SVG has to shrink its text to nothing at phone width; a grid reflows to one
 * column and keeps real type sizes. The only SVG here is the per-stage glyph,
 * where a vector actually earns its place.
 *
 * Server component: no state, no handlers, so it ships no JavaScript.
 */

type Stage = PipelineStage;

export default function PipelineFigure() {
  return (
    <figure className="w-full">
      <div className="grid gap-px overflow-hidden rounded-xl border border-slate-200 bg-slate-200 sm:grid-cols-2 lg:grid-cols-3">
        {PIPELINE_STAGES.map((s) => (
          <div
            key={s.n}
            className={[
              "relative flex flex-col gap-2 bg-white p-4",
              // The gates are the point, so they are the only cells with a
              // tint. Everything else stays white.
              s.gate ? "bg-blue-50/40" : "",
            ].join(" ")}
          >
            <div className="flex items-center gap-2">
              <span
                className={[
                  "flex size-7 shrink-0 items-center justify-center rounded-lg",
                  s.gate
                    ? "bg-[#2a78d6] text-white ring-2 ring-[#2a78d6]/20"
                    : "bg-slate-100 text-slate-500",
                ].join(" ")}
              >
                <Glyph kind={s.glyph} />
              </span>
              <h3 className="text-sm font-semibold text-slate-900">
                {s.title}
              </h3>
              {s.gate && (
                <span className="ml-auto rounded-full bg-[#2a78d6]/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-[#1b5fb0]">
                  Gate
                </span>
              )}
            </div>
            <p className="text-sm leading-relaxed text-slate-600">{s.body}</p>
          </div>
        ))}
      </div>

      <figcaption className="mt-3 flex flex-wrap items-start gap-x-6 gap-y-2 text-xs text-slate-500">
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm bg-[#2a78d6]" aria-hidden="true" />
          A gate can only take verification away, never restore it
        </span>
        <span className="inline-flex items-center gap-1.5">
          <svg viewBox="0 0 10 10" className="size-2.5 text-red-600" aria-hidden="true">
            <path d="M5 0.5 L9.5 9 L0.5 9 Z" fill="currentColor" />
          </svg>
          A register that fails stage 3 reaches no generator at all
        </span>
      </figcaption>
    </figure>
  );
}

function Glyph({ kind }: { kind: Stage["glyph"] }) {
  const common = {
    viewBox: "0 0 16 16",
    className: "size-4",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.5,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
  switch (kind) {
    case "page":
      return (
        <svg {...common}>
          <path d="M3.5 1.5h6l3 3v10h-9z" />
          <path d="M9.5 1.5v3h3M5.5 8h5M5.5 11h5" />
        </svg>
      );
    case "eye":
      return (
        <svg {...common}>
          <path d="M1 8s2.5-4.5 7-4.5S15 8 15 8s-2.5 4.5-7 4.5S1 8 1 8z" />
          <circle cx="8" cy="8" r="1.75" />
        </svg>
      );
    case "proof":
      // A balance: the gate weighs a claim rather than trusting it.
      return (
        <svg {...common}>
          <path d="M8 2v12M3 5h10M5 5l-2 4h4zM11 5l-2 4h4zM5.5 14h5" />
        </svg>
      );
    case "code":
      return (
        <svg {...common}>
          <path d="M5.5 4.5 2 8l3.5 3.5M10.5 4.5 14 8l-3.5 3.5" />
        </svg>
      );
    case "chip":
      return (
        <svg {...common}>
          <rect x="4.5" y="4.5" width="7" height="7" rx="1" />
          <path d="M6.5 1.5v3M9.5 1.5v3M6.5 11.5v3M9.5 11.5v3M1.5 6.5h3M1.5 9.5h3M11.5 6.5h3M11.5 9.5h3" />
        </svg>
      );
    case "check":
      return (
        <svg {...common}>
          <path d="M2.5 8.5l3.5 3.5 7.5-8" />
        </svg>
      );
  }
}
