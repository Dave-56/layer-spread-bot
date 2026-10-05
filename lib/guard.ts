// Only this app, open on this machine, may call the engine through it.
//
// The engine can place orders and add strategy files (which run as code), so a request from any other
// website open in the same browser must never reach it:
// - Host must be this machine's own name and port. A site whose name points at 127.0.0.1 (DNS
//   rebinding) sends its own name, so it's refused.
// - A request that changes anything (not GET) must come from this app's own page: the browser says
//   so with Sec-Fetch-Site: same-origin, or an Origin equal to this app's own. A request that says
//   neither is refused.

export const PROXY_HEADER = "x-spread-proxy"; // the engine refuses a POST without it

const LOCAL_NAMES = ["127.0.0.1", "localhost", "[::1]"];

function port(): string {
  return process.env.WEB_PORT ?? "3200";
}

/** null when the request may go on; otherwise the 403 to send back. */
export function refuse(request: Request, webPort: string = port()): Response | null {
  const host = (request.headers.get("host") ?? "").toLowerCase();
  if (!LOCAL_NAMES.some((n) => host === `${n}:${webPort}`)) {
    return Response.json({ error: "This app answers only at its own address on this machine." }, { status: 403 });
  }
  if (request.method === "GET" || request.method === "HEAD") return null;
  const site = request.headers.get("sec-fetch-site");
  const origin = request.headers.get("origin");
  const sameOrigin = site ? site === "same-origin" : origin === `http://${host}`;
  if (!sameOrigin) {
    return Response.json({ error: "Only this app's own page can do that." }, { status: 403 });
  }
  return null;
}
