import { ArrowRight, Play, Upload } from "lucide-react";
import Link from "next/link";

import CopyCommand from "@/components/CopyCommand";
import PipelineFigure from "@/components/figures/PipelineFigure";
import RegisterStrip from "@/components/figures/RegisterStrip";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { findSvd, isReserved, parseSvd } from "@/lib/bitfields";
import { listChips, loadRun } from "@/lib/fixtures";
import { loadArtifacts } from "@/lib/pipeline";
import { checkScore, summarize } from "@/lib/run";
import { CHIP_WORDING } from "@/lib/wording";

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

  // The hero figure, from the featured run's own generated SVD. The widest
  // register is chosen because it carries the most fields, which is the point
  // being made; a 2-field register would undersell it.
  const heroSvd = featured ? findSvd(await loadArtifacts(featured.chip)) : null;
  const heroMaps = heroSvd ? parseSvd(heroSvd) : [];
  const heroMap =
    heroMaps.length > 0
      ? heroMaps.reduce((a, b) => (b.fields.length > a.fields.length ? b : a))
      : null;
  const heroFieldCount = heroMap
    ? heroMap.fields.filter((f) => !isReserved(f.name)).length
    : 0;
  const heroBase = featured ? featured.summary.baseAddress : null;

  return (
    <div className="shell py-14 sm:py-20">
      <h1 className="max-w-4xl text-balance text-3xl font-semibold leading-[1.15] tracking-tight text-slate-900 sm:text-4xl">
        A chip manual is 3,000 pages. Getting one number wrong kills the board.
      </h1>
      <p className="mt-5 max-w-2xl text-lg leading-relaxed text-slate-600">
        To talk to a chip, a programmer reads its PDF manual and copies hundreds
        of addresses and bit positions into code by hand. One typo writes to the
        wrong place, and on a power chip that can destroy the hardware.
        SiliconTruth reads the manual, writes that code, and then proves the
        code matches the page it came from.
      </p>

      {/* Two doors, and the order is deliberate: watching costs nothing and
          needs no key, running your own needs both a key and Docker. */}
      <div className="mt-9 grid gap-4 sm:grid-cols-2">
        {featured && (
          <Card className="border-slate-200 bg-white shadow-sm ring-1 ring-slate-900/[0.03]">
            <CardContent className="flex h-full flex-col gap-3 p-5">
              <div className="flex-1">
                <p className="text-sm font-semibold text-slate-900">
                  Watch a run, start to finish
                </p>
                <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-slate-600">
                  {featured.steps} steps, replayed one at a time, about{" "}
                  {Math.round((featured.steps * 520) / 1000)} seconds. Nothing
                  to install and no key.
                </p>
              </div>
              <Button asChild className="w-fit">
                <Link href={`/replay/${featured.chip}`}>
                  <Play /> Watch the run
                </Link>
              </Button>
            </CardContent>
          </Card>
        )}

        <Card className="border-slate-900/10 bg-slate-900 text-white shadow-sm">
          <CardContent className="flex h-full flex-col gap-3 p-5">
            <div className="flex-1">
              <p className="text-sm font-semibold text-white">
                Run it on your own manual
              </p>
              <p className="mt-1.5 text-sm leading-relaxed text-slate-300">
                Upload the PDF, name the pages, and watch the same three panes
                fill in live. Needs a key on the server and Docker for the
                execution gate.
              </p>
            </div>
            <Button
              asChild
              className="w-fit bg-white text-slate-900 hover:bg-slate-100"
            >
              <Link href="/live">
                <Upload /> Upload a PDF
              </Link>
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* The figure, before the prose. "One wrong number" is abstract until
          you see a register drawn as the 32 bits it is. */}
      {heroMap && (
        <section className="mt-14">
          <h2 className="text-sm font-semibold text-slate-900">
            This is what one register looks like
          </h2>
          <p className="mt-1.5 max-w-prose text-sm leading-relaxed text-slate-600">
            {heroFieldCount} separate settings packed into {heroMap.width} bits
            of one address. Every boundary has to be read off a table in a PDF,
            exactly — get one edge wrong and the driver writes to the wrong
            setting. Hatched bits are reserved. Hover a field for its range.
          </p>
          <div className="mt-5 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
            <RegisterStrip map={heroMap} baseAddress={heroBase} fieldTable />
          </div>
          <p className="mt-2.5 max-w-2xl text-xs leading-relaxed text-slate-500">
            Drawn from the CMSIS-SVD this project generated for{" "}
            <span className="font-mono">{featured?.chip}</span> — so it shows
            what survived the checks, not what the model claimed.
          </p>
        </section>
      )}

      <section className="mt-14">
        <h2 className="text-sm font-semibold text-slate-900">
          How a number gets trusted
        </h2>
        <p className="mt-1.5 max-w-prose text-sm leading-relaxed text-slate-600">
          Six stages, two of which are gates. The gates are the whole design:
          the first means no model output reaches a generator unproved, the
          second means no generated code is called correct unexecuted.
        </p>
        <div className="mt-5">
          <PipelineFigure />
        </div>
      </section>

      <h2 className="mt-14 text-sm font-semibold text-slate-900">
        Or run it from the terminal
      </h2>
      <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-slate-600">
        One command now does the whole thing: it reads the pages, refuses to
        write anything that fails a check, generates the driver from what
        survived, then compiles and executes it.
      </p>
      <div className="mt-3 max-w-5xl space-y-2">
        <CopyCommand command="silicontruth pipeline manual.pdf --pages 412 --chip stm32h7 --peripheral USART1 --base 0x40011000 --errata errata.pdf -o out/stm32h7" />
      </div>

      <h2 className="mt-14 text-sm font-semibold text-slate-900">Recorded runs</h2>
      <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-slate-600">
        These pages are datasheets generated to match the layout of a real
        reference manual. No manufacturer PDF has been run through this yet.
      </p>

      <div className="mt-4 divide-y divide-slate-200 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        {featured && <RunRow {...featured} />}
        {others.map((r) => (
          <RunRow key={r.chip} {...r} />
        ))}
      </div>

      {others.length > 0 && (
        // Said out loud, because "1 passed, 3 not run" otherwise reads as "the
        // checks mostly do not work" rather than "this run never reached them".
        <p className="mt-3 max-w-2xl text-sm text-muted-foreground">
          The runs below the first one started from a register map that had
          already been read, so the checks that look at the page had nothing to
          look at. They show as not run rather than assumed to pass.
        </p>
      )}

      <p className="mt-10 max-w-2xl text-sm leading-relaxed text-muted-foreground">
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
            className={score.passed > 0 ? "text-emerald-700" : "text-slate-400"}
          >
            {score.passed} passed
          </span>
          {score.failed > 0 && (
            <span className="text-red-700">, {score.failed} failed</span>
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
