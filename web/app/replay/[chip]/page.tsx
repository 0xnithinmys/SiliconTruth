import { notFound } from "next/navigation";

import Workbench from "@/components/Workbench";
import { listChips, loadRun, parseTrace } from "@/lib/fixtures";
import { loadPages } from "@/lib/pages";
import { loadArtifacts, loadSummary } from "@/lib/pipeline";

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

export default async function ReplayPage({
  params,
}: {
  params: Promise<{ chip: string }>;
}) {
  const { chip } = await params;
  const events = await loadRun(chip);
  if (events.length === 0) notFound();

  // Everything shown comes from the recorded run or the fixture directory.
  // The old route hardcoded four `usart1_*` filenames and a base address of
  // 0x40011000, which is wrong for four of the five benchmark chips.
  const summary = await loadSummary(chip, events);
  const artifacts = await loadArtifacts(chip);

  const traceEvent = events.find((e) => e.kind === "renode_trace");
  const transactions = traceEvent ? parseTrace(String(traceEvent.text ?? "")) : [];

  const pages = await loadPages(chip);

  return (
    <Workbench
      chip={chip}
      events={events}
      summary={summary}
      artifacts={artifacts}
      transactions={transactions}
      pages={pages}
    />
  );
}
