/**
 * T-104c — live-run proxy.
 *
 * THE POINT OF THIS FILE: MODEL_API_KEY is read here, on the server, and never
 * reaches the browser. A Vite SPA would have to either ship the key in the
 * bundle or stand up a separate backend to hold it; a Route Handler means one
 * deployable instead of two.
 *
 * Note the absence of NEXT_PUBLIC_. Anything with that prefix is compiled into
 * the client bundle and is world-readable. Credentials never get it.
 */
import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface RunRequest {
  chip?: string;
  peripheral?: string;
}

export async function POST(req: NextRequest) {
  const key = process.env.MODEL_API_KEY;
  const modalUrl = process.env.MODAL_RUN_URL;

  if (!key) {
    return NextResponse.json(
      {
        status: "UNAVAILABLE",
        reason: "no_inference_key",
        message:
          "MODEL_API_KEY is not configured on the server. Live mode is off; " +
          "use replay mode, which needs no credentials.",
      },
      { status: 503 },
    );
  }

  if (!modalUrl) {
    return NextResponse.json(
      {
        status: "UNAVAILABLE",
        reason: "no_verification_container",
        message:
          "MODAL_RUN_URL is not configured. The Z3 and Renode gates run in the " +
          "Modal container; without it a live run cannot be verified, and an " +
          "unverified run is not something this tool will report as a result.",
      },
      { status: 503 },
    );
  }

  let body: RunRequest;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ status: "ERROR", message: "body must be JSON" }, { status: 400 });
  }

  try {
    const upstream = await fetch(modalUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${key}` },
      body: JSON.stringify({ chip: body.chip, peripheral: body.peripheral }),
      signal: AbortSignal.timeout(180_000),
    });

    const text = await upstream.text();
    if (!upstream.ok) {
      // Surface the vendor's own message. A 402 here is actionable by a human,
      // not by a retry, and saying so beats a generic failure.
      return NextResponse.json(
        {
          status: "FAIL",
          reason: upstream.status === 402 ? "billing_blocked" : "upstream_error",
          http: upstream.status,
          message: text.slice(0, 600),
        },
        { status: 502 },
      );
    }
    return new NextResponse(text, {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  } catch (e) {
    return NextResponse.json(
      { status: "ERROR", message: e instanceof Error ? e.message : String(e) },
      { status: 500 },
    );
  }
}

export async function GET() {
  // Capability probe, so the UI can grey out live mode instead of offering a
  // button that fails. Returns booleans only -- never the key itself.
  return NextResponse.json({
    live_available: Boolean(process.env.MODEL_API_KEY && process.env.MODAL_RUN_URL),
    has_key: Boolean(process.env.MODEL_API_KEY),
    has_container: Boolean(process.env.MODAL_RUN_URL),
  });
}
