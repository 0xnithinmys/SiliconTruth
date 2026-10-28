"use client";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { fileCaption } from "@/lib/wording";

/**
 * The code that came out, one tab per file.
 *
 * Filenames like chip.svd mean nothing to a visitor, so each tab carries a
 * one-line caption saying what the file is for. Lines carrying an errata
 * workaround are tinted, because "the generated driver already handles a
 * published silicon bug" is the single most surprising thing here.
 */
export default function CodePane({
  artifacts,
  midRun,
}: {
  artifacts: Record<string, string>;
  /** True while the player is part way through. "Nothing generated" and "not
   *  generated yet" are different statements and the pane must not make the
   *  first one while the second is true. */
  midRun?: boolean;
}) {
  const names = Object.keys(artifacts);

  if (names.length === 0) {
    return (
      <div className="p-4 text-sm text-muted-foreground">
        {midRun
          ? "Nothing written yet. The generator runs once every check has passed."
          : "No files were generated in this run."}
      </div>
    );
  }

  return (
    <Tabs defaultValue={names[0]} className="flex h-full min-h-0 flex-col gap-0">
      <div className="shrink-0 border-b p-2">
        <TabsList variant="line" className="h-auto w-full justify-start overflow-x-auto">
          {names.map((n) => (
            <TabsTrigger key={n} value={n} className="flex-none font-mono text-xs">
              {n}
            </TabsTrigger>
          ))}
        </TabsList>
      </div>

      {names.map((n) => {
        const caption = fileCaption(n);
        const lines = artifacts[n].split("\n");
        return (
          <TabsContent
            key={n}
            value={n}
            className="flex min-h-0 flex-1 flex-col data-inactive:hidden"
          >
            {caption && (
              <p className="shrink-0 border-b bg-muted/30 px-4 py-2 text-sm text-muted-foreground">
                {caption}
              </p>
            )}
            <pre className="min-h-0 flex-1 overflow-auto p-3 font-mono text-xs leading-relaxed">
              {lines.map((line, i) => (
                <div
                  key={i}
                  className={
                    line.includes("ERRATUM")
                      ? "bg-amber-50 text-amber-900"
                      : isComment(line)
                        ? "text-muted-foreground"
                        : "text-slate-700"
                  }
                >
                  <span className="mr-3 select-none text-slate-300">
                    {String(i + 1).padStart(3)}
                  </span>
                  {line || " "}
                </div>
              ))}
            </pre>
          </TabsContent>
        );
      })}
    </Tabs>
  );
}

function isComment(line: string): boolean {
  const t = line.trimStart();
  return (
    t.startsWith("*") ||
    t.startsWith("/*") ||
    t.startsWith("//") ||
    t.startsWith("#") ||
    t.startsWith("<!--")
  );
}
