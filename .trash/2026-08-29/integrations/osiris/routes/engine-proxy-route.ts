import { NextRequest } from 'next/server';

/**
 * OSIRIS → PYTHIA engine proxy.
 * Same-origin passthrough so the browser avoids CORS and SSE works cleanly.
 * /api/engine/<path>  ->  ${PYTHIA_ENGINE_URL}/<path>
 */
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const ENGINE = (process.env.PYTHIA_ENGINE_URL || 'http://localhost:8088').replace(/\/$/, '');

async function proxy(req: NextRequest, path: string[]): Promise<Response> {
  const sub = '/' + (path || []).join('/');
  const url = ENGINE + sub + (req.nextUrl.search || '');
  const isSSE = sub.endsWith('/stream');

  const init: RequestInit = {
    method: req.method,
    headers: { 'Content-Type': req.headers.get('content-type') || 'application/json' },
    // @ts-expect-error - duplex required by undici for streaming request bodies
    duplex: 'half',
  };
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    init.body = await req.text();
  }

  try {
    const upstream = await fetch(url, init);
    if (isSSE) {
      // Explicitly pump chunks so the dev server doesn't buffer the stream.
      const stream = new ReadableStream({
        async start(controller) {
          const reader = upstream.body!.getReader();
          try {
            for (;;) {
              const { done, value } = await reader.read();
              if (done) break;
              controller.enqueue(value);
            }
          } catch { /* upstream closed */ } finally {
            try { controller.close(); } catch { /* already closed */ }
          }
        },
        cancel() { try { upstream.body?.cancel(); } catch { /* noop */ } },
      });
      return new Response(stream, {
        status: upstream.status,
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache, no-transform',
          Connection: 'keep-alive',
          'X-Accel-Buffering': 'no',
        },
      });
    }
    const body = await upstream.text();
    return new Response(body, {
      status: upstream.status,
      headers: { 'Content-Type': upstream.headers.get('content-type') || 'application/json' },
    });
  } catch (e) {
    return new Response(JSON.stringify({ error: 'PYTHIA engine unreachable', detail: String(e), engine: ENGINE }), {
      status: 502,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, (await ctx.params).path);
}
export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, (await ctx.params).path);
}
