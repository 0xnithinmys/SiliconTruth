import { NextRequest, NextResponse } from "next/server";

/**
 * A password on live mode, and nothing else.
 *
 * `/live` and `/api/run` spend money: every run calls a paid inference API on
 * the server's key and burns CPU starting a Renode container. A public URL
 * with no gate is an open relay to someone else's billing account.
 *
 * The rest of the site stays open on purpose. The landing page and
 * `/replay/<chip>` are prerendered and keyless — that is the whole demo, it
 * costs nothing per visitor, and putting it behind a password would throw
 * away the one property the project keeps advertising.
 *
 * Basic auth rather than a login page: there are no accounts here, it is one
 * shared secret, and the browser remembers it for the session. If
 * LIVE_PASSWORD is unset the gate is off, which is what local development
 * wants.
 */
export const config = {
  matcher: ["/live/:path*", "/api/run/:path*"],
};

export function middleware(req: NextRequest) {
  const expected = process.env.LIVE_PASSWORD;
  if (!expected) {
    // FAIL CLOSED in production. An unset password opening the gate is the
    // right default on a laptop and exactly the wrong one on a public
    // server: a misconfigured deploy would quietly expose a paid inference
    // key to the internet, and the failure would look like success.
    if (process.env.NODE_ENV === "production") {
      return new NextResponse(
        "Live mode is disabled: this server has no LIVE_PASSWORD configured. " +
          "The recorded runs need no password: go to /.",
        { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8" } },
      );
    }
    return NextResponse.next();
  }

  const header = req.headers.get("authorization") ?? "";
  const [scheme, encoded] = header.split(" ");
  if (scheme === "Basic" && encoded) {
    let decoded = "";
    try {
      decoded = atob(encoded);
    } catch {
      decoded = "";
    }
    // Everything after the first colon is the password, so a password
    // containing a colon still works.
    const sep = decoded.indexOf(":");
    const supplied = sep >= 0 ? decoded.slice(sep + 1) : "";
    if (timingSafeEqual(supplied, expected)) return NextResponse.next();
  }

  return new NextResponse(
    "Live mode runs the pipeline on this server's inference key, so it is " +
      "password protected. The recorded runs need no password: go to /.",
    {
      status: 401,
      headers: {
        "WWW-Authenticate": 'Basic realm="SiliconTruth live mode", charset="UTF-8"',
        "Content-Type": "text/plain; charset=utf-8",
      },
    },
  );
}

/** Compared in constant time, so a wrong guess does not leak its length or
 *  how many characters matched through response timing. */
function timingSafeEqual(a: string, b: string): boolean {
  const len = Math.max(a.length, b.length);
  let diff = a.length ^ b.length;
  for (let i = 0; i < len; i++) {
    diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  }
  return diff === 0;
}
