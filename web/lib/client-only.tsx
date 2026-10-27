/**
 * T-104b — the ssr:false pattern, established once.
 *
 * pdf.js, @meta-sam/graphics, @monaco-editor/react and xterm.js all touch
 * `window`, `document` or `canvas` at module scope. Under SSR they throw
 * "DOMMatrix is not defined" or "window is not defined", and crucially that
 * only surfaces at BUILD time, never in `next dev` -- which is how it reaches
 * a deploy on the last day.
 *
 * Every pane in this workbench loads through here. Server components do one
 * job: read fixture JSON and pass it down as props.
 */
import dynamic from "next/dynamic";
import type { ComponentType } from "react";

export function clientOnly<P extends object>(
  loader: () => Promise<{ default: ComponentType<P> }>,
  label = "pane",
) {
  return dynamic(loader, {
    ssr: false,
    loading: () => (
      <div className="flex h-full items-center justify-center text-xs text-neutral-500">
        loading {label}…
      </div>
    ),
  });
}
