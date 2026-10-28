/**
 * Every word the UI shows a visitor, in one file.
 *
 * The pipeline's own vocabulary is Z3, SVD, MMIO, IR, errata. A visitor who
 * has never written a device driver does not know any of it, and a demo they
 * cannot read is a demo they cannot judge. So each thing gets two names: a
 * plain one that leads, and the real technical one kept beside it for the
 * people who want it.
 *
 * Keeping them here, rather than inline in the panes, means the landing page
 * and the workbench cannot describe the same gate two different ways.
 */

export interface Wording {
  /** What it is, in words anyone can read. */
  plain: string;
  /** The name an embedded engineer would use. */
  technical: string;
  /** One sentence on what passing it rules out. */
  proves: string;
}

/** The four gates, in the order they run. */
export const GATE_WORDING: Record<string, Wording> = {
  z3: {
    plain: "The numbers add up",
    technical: "Z3 SMT solver",
    proves:
      "Every register sits at a legal address and no two settings claim the same bit.",
  },
  names: {
    plain: "The names are really on the page",
    technical: "Text-layer corroboration",
    proves:
      "Every setting name in the output is printed in the PDF, so none was invented.",
  },
  grid: {
    plain: "Each setting is in the right column",
    technical: "Grid-column corroboration",
    proves:
      "A name sits under the bit number the page prints above it, so nothing slid sideways.",
  },
  renode: {
    plain: "The driver runs on a simulated chip",
    technical: "Renode MMIO oracle",
    proves:
      "The generated code is executed and every read and write it makes is checked against the manual.",
  },
};

/** Status words. "Not run" is deliberately not a failure and not a pass. */
export const STATUS_WORDING = {
  pass: "Passed",
  fail: "Failed",
  unavailable: "Skipped",
  missing: "Not run",
} as const;

/** The recorded run, step by step, for the timeline. */
export const STEP_WORDING: Record<string, string> = {
  run_start: "Run started",
  page_render: "Page turned into an image",
  sam_mask: "Register table found on the page",
  ir_extracted: "Register read off the page",
  z3_audit: "Numbers checked",
  z3_retry: "Page re-read at higher resolution",
  name_audit: "Names checked against the page",
  grid_audit: "Columns checked",
  errata_linked: "Known chip bugs cross-referenced",
  svd_emitted: "Register map written",
  hal_emitted: "Driver written",
  artifact: "File written",
  worktree: "Work split across agents",
  renode_trace: "Simulated chip run",
  verdict: "Verdict",
  run_end: "Run finished",
  error: "Error",
};

export function stepLabel(kind: string): string {
  return STEP_WORDING[kind] ?? kind.replace(/_/g, " ");
}

/** What each generated file is for. Shown under the code tabs, because
 *  "chip.svd" tells a visitor nothing at all. */
const FILE_WORDING: { match: RegExp; plain: string }[] = [
  { match: /\.svd$/, plain: "The register map, in the format debuggers and IDEs read" },
  { match: /_hal\.h$/, plain: "The driver's header: every register and setting as a constant" },
  { match: /_hal\.c$/, plain: "The driver itself, in C, with the chip's known bugs worked around" },
  { match: /_hal\.rs$/, plain: "The same driver in Rust, for firmware that does not use C" },
  { match: /mock\.py$/, plain: "A fake version of the chip, so the driver can be run without hardware" },
  { match: /\.repl$/, plain: "The simulated board the driver is loaded onto" },
  { match: /\.resc$/, plain: "The script that boots the simulator and runs the test" },
];

export function fileCaption(name: string): string | null {
  return FILE_WORDING.find((f) => f.match.test(name))?.plain ?? null;
}

/** The pitch, in three steps. Used on the landing page and nowhere else, but
 *  it belongs with the rest of the copy. */
export const HOW_IT_WORKS = [
  {
    step: "1",
    title: "Read the manual",
    body:
      "A chip's manual is a PDF of dense tables. The model is shown the page as an image and reports what each register and setting is.",
  },
  {
    step: "2",
    title: "Check every claim",
    body:
      "Nothing the model says is trusted. Four independent checks run against the page itself, and anything that fails is marked unverified and left out of the code.",
  },
  {
    step: "3",
    title: "Write the driver",
    body:
      "What survives becomes a register map, a C and a Rust driver with the chip's published bugs already worked around, and a simulated chip to run them on.",
  },
] as const;

/** Display names for the recorded runs.
 *
 *  The directory names are fixture slugs. "uart32" and "stm32h7_errata" mean
 *  something to whoever recorded them and nothing to anyone else.
 *
 *  Note what these are NOT called: real chip manuals. benchmarks/scorecard.json
 *  says `"synthetic": true`, and the pages were generated to match the layout
 *  of a reference manual, not scanned from one. Saying otherwise on the
 *  landing page of a project whose entire pitch is "we do not overclaim"
 *  would be the worst possible place to start.
 */
export const CHIP_WORDING: Record<string, { title: string; note: string }> = {
  uart32: {
    title: "UART peripheral",
    note: "Synthetic datasheet, laid out like an STM32 USART chapter. Read from the page, checked, and generated end to end.",
  },
  stm32h7: {
    title: "STM32H743 USART1",
    note: "Generated from a register map that was already verified.",
  },
  stm32h7_errata: {
    title: "STM32H743 USART1, with errata",
    note: "The same map, with the published silicon bugs applied.",
  },
  synthetic: {
    title: "Synthetic USART",
    note: "Generated from a register map that was already verified.",
  },
};

export function chipTitle(chip: string): string {
  return CHIP_WORDING[chip]?.title ?? chip;
}
