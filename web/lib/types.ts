/** Shapes mirrored from the Python side. Keep in sync with
 *  silicontruth/replay/recorder.py and silicontruth/oracle/renode_oracle.py. */

export type EventKind =
  | "run_start" | "page_render" | "sam_mask" | "ir_extracted"
  | "z3_audit" | "z3_retry"
  // The two page-corroboration gates. Separate kinds, not one "verified"
  // flag: they fail for different reasons and the UI has to say which.
  | "name_audit" | "grid_audit" | "errata_linked"
  | "svd_emitted" | "hal_emitted"
  | "artifact" | "worktree" | "renode_trace" | "verdict"
  | "run_end" | "error";

export interface RunEvent {
  kind: EventKind;
  t_ms: number;
  [key: string]: unknown;
}

export interface MmioTransaction {
  kind: "READ" | "WRITE";
  offset: number;
  register: string;
  value: number;
  verdict: "PASS" | "FAIL";
  note?: string;
}

export interface ChipSummary {
  chip: string;
  peripheral: string;
  events: number;
  duration_ms: number;
  status: string;
  artifacts: string[];
}

export interface FixtureIndex {
  schema: number;
  chips: ChipSummary[];
}
