import LiveWorkspace from "@/components/LiveWorkspace";
import { describeCapabilities } from "@/lib/runner";

/**
 * Your own PDF, read live.
 *
 * Dynamic on purpose, and the only route in the app that is. The replay
 * routes stay prerendered and keyless — opening one still makes no API call —
 * so adding this does not cost the guarantee the landing page makes. It is
 * the opt-in half: it needs a key on the server and Docker on the host, and
 * it says so before offering a button rather than after failing.
 */
export const dynamic = "force-dynamic";

export const metadata = {
  title: "Run your own manual — SiliconTruth",
  description:
    "Upload a chip reference manual and watch SiliconTruth read it, generate the driver, and execute it.",
};

export default function LivePage() {
  // Read on the server. The booleans cross to the client; the key never does.
  const caps = describeCapabilities();

  return (
    <main className="flex min-h-[calc(100vh-3.5rem)] flex-col">
      <LiveWorkspace
        liveAvailable={caps.live_available}
        unavailableReason={caps.reason}
      />
    </main>
  );
}
