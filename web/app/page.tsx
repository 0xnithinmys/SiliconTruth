import { ArrowRight, Play } from "lucide-react";
import Link from "next/link";

import CopyCommand from "@/components/CopyCommand";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { listChips, loadRun } from "@/lib/fixtures";
import { checkScore, summarize } from "@/lib/run";
import { CHIP_WORDING, HOW_IT_WORKS } from "@/lib/wording";

/**
 * T-133 — the landing page defaults to replay. A visitor with ninety seconds
 * and no patience must see a working demo immediately: no key, no signup, no
 * backend, no cold start.
 *
 * It has to do three things in order: say what problem this solves to someone
 * who has never written firmware, put them one click from watching it work,
 * and tell them how to run it on their own PDF. Anything that is not one of
 * those three is in the way.
 */
export default async function Home() {
  const chips = await listChips();
  const runs = (
    await Promise.all(
      chips.map(async (chip) => {
        const events = await loadRun(chip);
        const summary = summarize(chip, events);
        return {
          chip,
          summary,
          score: checkScore(summary.gates),
          steps: events.length,
          // A run that read a page is a full demo. One generated from an
          // already-verified map is not, and the two should not sit in the
          // same list pretending to be the same thing.
          readFromPage: summary.registers.length > 0,
        };
      }),
    )
  ).filter((r) => r.steps > 0);

  const featured = runs.find((r) => r.readFromPage);
  const others = runs.filter((r) => r !== featured);

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

      {featured && (
        <Card className="mt-8 border-emerald-500/30 bg-emerald-500/5">
          <CardContent className="flex flex-wrap items-center justify-between gap-4">
            <div className="min-w-0">
              <p className="text-sm font-medium">
                Watch it read a datasheet and write the driver
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                {featured.steps} steps, replayed one at a time, about{" "}
                {Math.round((featured.steps * 520) / 1000)} seconds. Nothing to
                install and no key.
              </p>
            </div>
            <Button asChild>
              <Link href={`/replay/${featured.chip}`}>
                <Play /> Watch the run
              </Link>
            </Button>
          </CardContent>
        </Card>
      )}

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

      <h2 className="mt-12 text-sm font-semibold">Run it on your own PDF</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Two commands. The first reads the pages and refuses to write anything
        that fails a check; the second generates the driver from what survived.
      </p>
      <div className="mt-3 space-y-2">
        <CopyCommand command="silicontruth extract manual.pdf --pages 412 --chip stm32h7 --peripheral USART1 --base 0x40011000 --errata errata.pdf -o out/ir.json" />
        <CopyCommand command="silicontruth build out/ir.json -o out/stm32h7" />
      </div>

      <h2 className="mt-12 text-sm font-semibold">Recorded runs</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        These pages are datasheets generated to match the layout of a real
        reference manual. No manufacturer PDF has been run through this yet.
      </p>

      <div className="mt-4 divide-y overflow-hidden rounded-lg border">
        {featured && <RunRow {...featured} />}
        {others.map((r) => (
          <RunRow key={r.chip} {...r} />
        ))}
      </div>

      {others.length > 0 && (
        // Said out loud, because "1 passed, 3 not run" otherwise reads as "the
        // checks mostly do not work" rather than "this run never reached them".
        <p className="mt-3 text-sm text-muted-foreground">
          The runs below the first one started from a register map that had
          already been read, so the checks that look at the page had nothing to
          look at. They show as not run rather than assumed to pass.
        </p>
      )}

      <p className="mt-10 text-sm leading-relaxed text-muted-foreground">
        Every page here is a static file recorded from a real pipeline run. Open
        your browser network tab: there are no API calls, and nothing here needs
        a key.
      </p>
    </div>
  );
}

function RunRow({
  chip,
  summary,
  score,
  readFromPage,
}: {
  chip: string;
  summary: ReturnType<typeof summarize>;
  score: ReturnType<typeof checkScore>;
  readFromPage: boolean;
}) {
  const words = CHIP_WORDING[chip];
  return (
    <Link
      href={`/replay/${chip}`}
      className="flex items-center justify-between gap-4 px-4 py-3.5 transition-colors hover:bg-muted/50"
    >
      <div className="min-w-0">
        <p className="flex items-center gap-2 text-sm font-medium">
          {words?.title ?? chip}
          {readFromPage && (
            <Badge variant="secondary" className="font-normal">
              reads the PDF
            </Badge>
          )}
        </p>
        <p className="mt-0.5 text-sm text-muted-foreground">
          {words?.note ?? `${summary.peripheral}, ${summary.registers.length} registers`}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <span className="text-sm">
          <span
            className={score.passed > 0 ? "text-emerald-400" : "text-muted-foreground"}
          >
            {score.passed} passed
          </span>
          {score.failed > 0 && (
            <span className="text-red-400">, {score.failed} failed</span>
          )}
          {score.notRun > 0 && (
            <span className="text-muted-foreground">, {score.notRun} not run</span>
          )}
        </span>
        <ArrowRight className="size-4 text-muted-foreground" />
      </div>
    </Link>
  );
}
