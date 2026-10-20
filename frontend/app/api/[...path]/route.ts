import type { NextRequest } from "next/server";

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

const hopByHopHeaders = [
  "connection",
  "content-length",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
];

async function proxyRequest(
  request: NextRequest,
  context: RouteContext,
): Promise<Response> {
  const { path } = await context.params;
  const backend = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";
  const target = new URL(
    `/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`,
    backend.endsWith("/") ? backend : `${backend}/`,
  );
  const headers = new Headers(request.headers);
  for (const header of hopByHopHeaders) headers.delete(header);

  const body =
    request.method === "GET" || request.method === "HEAD"
      ? undefined
      : await request.arrayBuffer();
  const upstream = await fetch(target, {
    method: request.method,
    headers,
    body,
    cache: "no-store",
    redirect: "manual",
  });
  const responseHeaders = new Headers(upstream.headers);
  for (const header of hopByHopHeaders) responseHeaders.delete(header);
  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}

export const GET = proxyRequest;
export const POST = proxyRequest;
export const PATCH = proxyRequest;
export const PUT = proxyRequest;
export const DELETE = proxyRequest;
export const HEAD = proxyRequest;
