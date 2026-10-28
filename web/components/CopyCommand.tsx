"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";

/** A command you can take away with one click.
 *
 *  A long CLI invocation printed as static text is a transcription exercise,
 *  and a visitor who wants to try this is exactly the visitor worth not
 *  annoying. */
export default function CopyCommand({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard access can be refused, and the command is on screen anyway.
    }
  }

  return (
    <div className="flex items-start gap-2 rounded-lg border bg-muted/40 p-3">
      <code className="min-w-0 flex-1 break-all font-mono text-xs leading-relaxed text-foreground/85">
        {command}
      </code>
      <Button
        size="icon"
        variant="ghost"
        onClick={copy}
        aria-label={copied ? "Copied" : "Copy command"}
      >
        {copied ? <Check className="text-emerald-400" /> : <Copy />}
      </Button>
    </div>
  );
}
