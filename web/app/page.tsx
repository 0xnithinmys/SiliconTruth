import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { listChips, loadRun } from "@/lib/fixtures";
import { loadSummary } from "@/lib/pipeline";
import { checkScore } from "@/lib/run";
import { HOW_IT_WORKS } from "@/lib/wording";

/**
 * T-133 — the landing page defaults to replay. A visitor with ninety seconds
 * and no patience must see a working demo immediately: no key, no signup, no
 * backend, no cold start.
 *
 * It also has to explain the idea to someone who has never written firmware,
 * so the problem comes before the vocabulary, and every run in the list
 * carries its real check score rather than an unqualified tick.
 */
export default async function Home() {
  const chips = await listChips();
  const runs = await Promise.all(
    chips.map(async (chip) => {
      const events = await loadRun(chip);
      const summary = await loadSummary(chip, events);
      return { chip, summary, score: checkScore(summary.gates) };
    }),
  );
  // Best-checked run first. The older fixtures were recorded before the two
  // page-corroboration checks existed, so they genuinely have less to show,
  // and burying the fullest run at the bottom of an alphabetical list is how
  // a visitor leaves thinking the checks mostly do not run.
  const ordered = [...runs].sort(
    (a, b) => b.score.passed - a.score.passed || a.chip.localeCompare(b.chip),
  );

  return (
    <div className="mx-auto max-w-3xl px-4 py-14">
      <h1 className="text-balance text-3xl font-semibold tracking-tight">
        A chip manual is 3,000 pages. Getting one number wrong kills the board.
      </h1>
      <p className="mt-4 text-lg leading-relaxed text-muted-foreground">
        To talk to a chip, a programmer reads its PDF manual and copies hundreds
        of addresses and bit positions into code by hand. One typo writes to the
        wrong place, and on a power chip that can destroy the hardware.
        SiliconTruth reads the manual, writes that code, and then proves the
        code matches the page it came from.
      </p>

      <div className="mt-10 grid gap-3 sm:grid-cols-3">
        {HOW_IT_WORKS.map((s) => (
          <Card key={s.step}>
            <CardContent className="space-y-1.5">
              <Badge variant="secondary" className="font-mono">
                {s.step}
              </Badge>
              <h2 className="text-sm font-semibold">{s.title}</h2>
              <p className="text-sm leading-relaxed text-muted-foreground">
                {s.body}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      <h2 className="mt-12 text-sm font-semibold">See a real run</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Each of these is a recorded run on a real chip manual. Open one to see
        the page, the code, and every check that ran.
      </p>

      {ordered.length === 0 ? (
        <Card className="mt-4 border-dashed">
          <CardContent className="text-sm text-muted-foreground">
            No runs recorded yet. Run{" "}
            <code className="font-mono text-foreground">
              silicontruth build &lt;ir.json&gt;
            </code>{" "}
            and the next build will pick the fixtures up.
          </CardContent>
        </Card>
      ) : (
        <div className="mt-4 divide-y overflow-hidden rounded-lg border">
          {ordered.map(({ chip, summary, score }) => (
            <Link
              key={chip}
              href={`/replay/${chip}`}
              className="flex items-center justify-between gap-4 px-4 py-3.5 transition-colors hover:bg-muted/50"
            >
              <div className="min-w-0">
                <p className="font-mono text-sm">{chip}</p>
                <p className="text-sm text-muted-foreground">
                  {summary.peripheral}
                  {summary.registers.length > 0 &&
                    `, ${summary.registers.length} register${
                      summary.registers.length === 1 ? "" : "s"
                    }`}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <span className="text-sm">
                  <span
                    className={
                      score.passed > 0 ? "text-emerald-400" : "text-muted-foreground"
                    }
                  >
                    {score.passed} passed
                  </span>
                  {score.failed > 0 && (
                    <span className="text-red-400">, {score.failed} failed</span>
                  )}
                  {score.notRun > 0 && (
                    <span className="text-muted-foreground">
                      , {score.notRun} not run
                    </span>
                  )}
                </span>
                <ArrowRight className="size-4 text-muted-foreground" />
              </div>
            </Link>
          ))}
        </div>
      )}

      {ordered.some((r) => r.score.notRun > 0) && (
        // Said out loud, because "1 passed, 3 not run" otherwise reads as
        // "the checks mostly do not work" rather than "this recording
        // predates them".
        <p className="mt-3 text-sm text-muted-foreground">
          A run recorded before a check existed shows that check as not run.
          Nothing here assumes a check would have passed.
        </p>
      )}

      <p className="mt-10 text-sm leading-relaxed text-muted-foreground">
        These pages are static files recorded from real pipeline runs. Open your
        browser network tab: there are no API calls, and nothing here needs a
        key.
      </p>
    </div>
  );
}
