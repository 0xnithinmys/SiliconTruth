/**
 * Live runs: POST a PDF to start one, GET to follow it.
 *
 * THE POINT OF THIS FILE, unchanged from when it was a Modal proxy:
 * MODEL_API_KEY is read here, on the server, and never reaches the browser.
 * Note the absence of NEXT_PUBLIC_ — anything with that prefix is compiled
 * into the client bundle and is world-readable. Credentials never get it.
 *
 * What changed is where the work happens. This used to proxy to MODAL_RUN_URL,
 * which was never deployed, so live mode was permanently 503 and no component
 * ever called it. It now drives `silicontruth pipeline` locally, which needs
 * no account anywhere: the same code path the CLI runs, recording the same
 * JSONL the static replays are built from.
 */
import { NextRequest, NextResponse } from "next/server";

import {
  describeCapabilities,
  getRun,
  pdfPageCount,
  startRun,
} from "@/lib/runner";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** 64 MB. A reference manual is large; a 2 GB upload is not a manual. */
const MAX_PDF_BYTES = 64 * 1024 * 1024;
const MAX_PAGES = 12;

/** The chip name becomes a DIRECTORY NAME and a process argument, so it is
 *  validated rather than trusted. Without this, a chip of "../../etc" writes
 *  the run wherever it likes. */
const SAFE_NAME = /^[A-Za-z0-9_-]{1,40}$/;

function bad(message: string, field?: string) {
  return NextResponse.json({ status: "ERROR", field, message }, { status: 400 });
}

export async function GET(req: NextRequest) {
  const id = req.nextUrl.searchParams.get("id");
  if (!id) {
    // No id: the capability probe, so the UI can explain itself before
    // offering a button that cannot work. Booleans only, never the key.
    return NextResponse.json(describeCapabilities());
  }
  const snapshot = await getRun(id);
  if (!snapshot) {
    return NextResponse.json(
      { status: "ERROR", message: `no run ${id}. The server may have restarted.` },
      { status: 404 },
    );
  }
  return NextResponse.json(snapshot);
}

export async function POST(req: NextRequest) {
  const caps = describeCapabilities();
  if (!caps.live_available) {
    return NextResponse.json(
      { status: "UNAVAILABLE", reason: "no_inference_key", message: caps.reason },
      { status: 503 },
    );
  }

  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return bad("the request body must be multipart/form-data with a `pdf` file");
  }

  const pdf = form.get("pdf");
  if (!(pdf instanceof File) || pdf.size === 0) {
    return bad("attach the reference manual as `pdf`", "pdf");
  }
  if (pdf.size > MAX_PDF_BYTES) {
    return bad(
      `that PDF is ${(pdf.size / 1e6).toFixed(0)} MB; the limit is ${MAX_PDF_BYTES / 1e6} MB`,
      "pdf",
    );
  }

  const chip = String(form.get("chip") ?? "").trim();
  const peripheral = String(form.get("peripheral") ?? "").trim();
  if (!SAFE_NAME.test(chip)) {
    return bad("chip may use letters, digits, dash and underscore only", "chip");
  }
  if (!SAFE_NAME.test(peripheral)) {
    return bad("peripheral may use letters, digits, dash and underscore only", "peripheral");
  }

  // Parsed here and never asked of the model. A base address is the one
  // number in this pipeline that a human supplies, because getting it from a
  // model is exactly the defect the project exists to prevent.
  const baseRaw = String(form.get("base") ?? "").trim();
  const base = Number.parseInt(baseRaw.replace(/^0[xX]/, ""), 16);
  if (!baseRaw || Number.isNaN(base) || base < 0 || base > 0xffffffff) {
    return bad("base address must be hex, e.g. 0x40011000", "base");
  }
  if (base % 4 !== 0) {
    return bad("base address must be 4-byte aligned", "base");
  }

  const pages = String(form.get("pages") ?? "")
    .split(/[\s,]+/)
    .filter(Boolean)
    .map((n) => Number.parseInt(n, 10));
  if (pages.length === 0 || pages.some((n) => !Number.isInteger(n) || n < 1)) {
    return bad("pages must be 1-indexed page numbers, e.g. 412 413", "pages");
  }
  if (pages.length > MAX_PAGES) {
    return bad(`at most ${MAX_PAGES} pages per run`, "pages");
  }

  // Checked against the document BEFORE anything is spawned. The default
  // placeholder is a realistic page number for a real manual, so a small
  // test PDF plus an untouched field is the obvious first thing a visitor
  // does -- and it used to cost them a failed run and a stack trace.
  const pdfBytes = Buffer.from(await pdf.arrayBuffer());
  const total = await pdfPageCount(pdfBytes);
  if (total !== null) {
    const missing = pages.filter((n) => n > total);
    if (missing.length > 0) {
      return bad(
        `that PDF has ${total} page${total === 1 ? "" : "s"}, so ` +
          `page ${missing.join(", ")} ${missing.length === 1 ? "does" : "do"} ` +
          `not exist`,
        "pages",
      );
    }
  }

  const errata = form.get("errata");
  const errataFile = errata instanceof File && errata.size > 0 ? errata : undefined;
  if (errataFile && errataFile.size > MAX_PDF_BYTES) {
    return bad("the errata PDF is over the size limit", "errata");
  }
  const errataPage = Number.parseInt(String(form.get("errataPage") ?? "1"), 10);

  try {
    const id = await startRun({
      chip,
      peripheral,
      base,
      pages,
      errataPage: Number.isInteger(errataPage) && errataPage > 0 ? errataPage : 1,
      pdf: { name: pdf.name, bytes: pdfBytes },
      errata: errataFile
        ? { name: errataFile.name, bytes: Buffer.from(await errataFile.arrayBuffer()) }
        : undefined,
      skipEmulate: String(form.get("skipEmulate") ?? "") === "true",
    });
    return NextResponse.json({ status: "STARTED", id, chip }, { status: 202 });
  } catch (e) {
    return NextResponse.json(
      { status: "ERROR", message: e instanceof Error ? e.message : String(e) },
      { status: 500 },
    );
  }
}
