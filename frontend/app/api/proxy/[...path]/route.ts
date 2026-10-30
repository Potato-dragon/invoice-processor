// Server-side proxy to the FastAPI backend. It adds the X-API-Key header so
// the key never reaches the browser.
import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const API = process.env.API_INTERNAL_URL || "http://localhost:8000";
const KEY = process.env.API_KEY || "change-me";

async function forward(req: NextRequest, { params }: { params: { path: string[] } }) {
  const url = `${API}/api/${params.path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers = new Headers();
  headers.set("X-API-Key", KEY);
  const ct = req.headers.get("content-type");
  if (ct) headers.set("content-type", ct);
  const init: RequestInit & { duplex?: string } = { method: req.method, headers, cache: "no-store" };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = req.body;
    init.duplex = "half";
  }
  try {
    const res = await fetch(url, init);
    const out = new Headers();
    for (const h of ["content-type", "content-disposition", "content-length"]) {
      const v = res.headers.get(h);
      if (v) out.set(h, v);
    }
    return new Response(res.body, { status: res.status, headers: out });
  } catch {
    return Response.json({ error: { code: "INTERNAL_ERROR", message: "The API is not reachable." } }, { status: 502 });
  }
}

export { forward as GET, forward as POST, forward as PATCH, forward as PUT, forward as DELETE };
