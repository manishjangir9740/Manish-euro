// Optional password gate for the whole app (set ELUNO_UI_PASSWORD). Any user name is accepted.
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function proxy(req: NextRequest) {
  const pw = process.env.ELUNO_UI_PASSWORD;
  if (!pw || req.nextUrl.pathname === "/healthz") return NextResponse.next();
  const header = req.headers.get("authorization") || "";
  if (header.startsWith("Basic ")) {
    const given = atob(header.slice(6)).split(":").slice(1).join(":");
    if (given === pw) return NextResponse.next();
  }
  return new NextResponse("Authentication required", { status: 401, headers: { "WWW-Authenticate": 'Basic realm="Eluno till"' } });
}

export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"] };
