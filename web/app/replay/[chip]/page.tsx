import { notFound } from "next/navigation";

import RunPlayer from "@/components/RunPlayer";
import { listChips, loadRun } from "@/lib/fixtures";
import { loadPages } from "@/lib/pages";
import { loadArtifacts } from "@/lib/pipeline";

/**
 * T-131 — statically rendered. generateStaticParams prerenders one route per
 * recorded chip at build time, so these are served from the edge cache with
 * zero API calls and no cold start.
 *
 * Verify in the build output: these routes must show as prerendered, not
 * dynamic. If they go dynamic, the keyless guarantee quietly stops holding.
 *
 * The server's whole job is to hand over the recorded events and the files.
 * Everything the visitor can drive lives in RunPlayer, on the client.
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

  return (
    <RunPlayer
      chip={chip}
      events={events}
      artifacts={await loadArtifacts(chip)}
      pages={await loadPages(chip)}
    />
  );
}
