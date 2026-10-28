import { notFound } from "next/navigation";

import Workbench from "@/components/Workbench";
import { listChips, loadArtifact, loadRun, parseTrace, z3From } from "@/lib/fixtures";
import { loadPages } from "@/lib/pages";

/**
 * T-131 — statically rendered. generateStaticParams prerenders one route per
 * recorded chip at build time, so these are served from the edge cache with
 * zero API calls and no cold start.
 *
 * Verify in the build output: these routes must show as prerendered, not
 * dynamic. If they go dynamic, the keyless guarantee quietly stops holding.
 */
export const dynamic = "force-static";
export const dynamicParams = false;

export async function generateStaticParams() {
  const chips = await listChips();
  return chips.map((chip) => ({ chip }));
}

const ARTIFACTS = [
  "usart1_hal.c",
  "usart1_hal.h",
  "chip.svd",
  "peripheral_mock.py",
];

export default async function ReplayPage({
  params,
}: {
  params: Promise<{ chip: string }>;
}) {
  const { chip } = await params;
  const events = await loadRun(chip);
  if (events.length === 0) notFound();

  const start = events.find((e) => e.kind === "run_start");
  const peripheral = String(start?.peripheral ?? "?");

  const artifacts: Record<string, string> = {};
  for (const name of ARTIFACTS) {
    const body = await loadArtifact(chip, name);
    if (body) artifacts[name] = body;
  }

  const traceEvent = events.find((e) => e.kind === "renode_trace");
  const transactions = traceEvent ? parseTrace(String(traceEvent.text ?? "")) : [];

  const pages = await loadPages(chip);
  const z3 = z3From(events);
  const unverified = (z3?.violations ?? []).slice(0, 8);

  return (
    <Workbench
      chip={chip}
      peripheral={peripheral}
      events={events}
      z3={z3}
      artifacts={artifacts}
      transactions={transactions}
      baseAddress={0x4001_1000}
      unverified={unverified}
      pages={pages}
    />
  );
}
