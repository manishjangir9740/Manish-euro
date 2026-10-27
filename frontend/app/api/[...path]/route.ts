// Same-origin proxy to the Python till API. The browser never learns BACKEND_URL or the API token.
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const BACKEND = (process.env.BACKEND_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

async function forward(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const url = `${BACKEND}/api/${path.join("/")}${req.nextUrl.search}`;
  const headers: Record<string, string> = {};
  if (process.env.ELUNO_API_TOKEN) headers["X-Api-Token"] = process.env.ELUNO_API_TOKEN;
  let body: string | undefined;
  if (req.method !== "GET") {
    headers["Content-Type"] = "application/json";
    body = await req.text();
  }
  try {
    const res = await fetch(url, { method: req.method, headers, body, cache: "no-store", signal: AbortSignal.timeout(60_000) });
    return new Response(await res.text(), {
      status: res.status,
      headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json({ error: "BackendUnavailable", message: "The till server is not reachable. Try again in a moment." }, { status: 502 });
  }
}

export const GET = forward;
export const POST = forward;
