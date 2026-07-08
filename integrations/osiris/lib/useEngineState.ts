'use client';

/**
 * useEngineState — one live view of the PYTHIA engine for the whole page.
 * Primary transport: SSE via the engine proxy (/api/engine/state/stream).
 * Fallback: the old 2.5s /state poll whenever the stream is down; SSE retries every 15s.
 */
import { useEffect, useRef, useState } from 'react';

export type Agent = { name: string; probability: number; note?: string };
export type Prediction = {
  id: string; statement: string; horizon: string; probability: number; reasoning: string;
  location?: string; lat?: number | null; lng?: number | null; agents?: Agent[];
  base_probability?: number | null; split?: boolean;
};
export type World = { event_count: number; domains: Record<string, number>; top_events: string[]; text?: string };
export type Run = { id?: string; stage: string; trigger: string; error?: string; elapsed_ms?: number };
export type Snap = {
  config?: { llm_model?: string; swarm_models?: Record<string, string> };
  generating?: boolean; loop_enabled?: boolean; last_run_ms?: number | null;
  world?: World | null; predictions?: Prediction[]; runs?: Run[];
  track_record?: Record<string, unknown>;
};

const E = (p: string) => `/api/engine${p}`;

export function useEngineState(): { snap: Snap; connected: boolean; live: boolean } {
  const [snap, setSnap] = useState<Snap>({});
  const [connected, setConnected] = useState(false);
  const [live, setLive] = useState(false);

  useEffect(() => {
    let stopped = false;
    let es: EventSource | null = null;
    let pollIv: ReturnType<typeof setInterval> | null = null;
    let retryIv: ReturnType<typeof setInterval> | null = null;

    const poll = async () => {
      try {
        const r = await fetch(E('/state'), { cache: 'no-store' });
        if (!r.ok) { if (!stopped) setConnected(false); return; }
        const d = await r.json();
        if (!stopped) { setSnap(d); setConnected(true); }
      } catch { if (!stopped) setConnected(false); }
    };
    const startPoll = () => { if (!pollIv) { poll(); pollIv = setInterval(poll, 2500); } };
    const stopPoll = () => { if (pollIv) { clearInterval(pollIv); pollIv = null; } };

    const connect = () => {
      if (stopped || es) return;
      es = new EventSource(E('/state/stream'));
      es.onopen = () => { if (stopped) return; setConnected(true); setLive(true); stopPoll(); if (retryIv) { clearInterval(retryIv); retryIv = null; } };
      es.onmessage = (ev) => {
        if (stopped) return;
        let m: any; try { m = JSON.parse(ev.data); } catch { return; }
        const p = m.payload;
        switch (m.kind) {
          case 'snapshot': setSnap(p); break;
          case 'predictions': setSnap((s) => ({ ...s, predictions: p, last_run_ms: Date.now() })); break;
          case 'world': setSnap((s) => ({ ...s, world: p })); break;
          case 'track': setSnap((s) => ({ ...s, track_record: p })); break;
          case 'generating': setSnap((s) => ({ ...s, generating: p.generating })); break;
          case 'loop': setSnap((s) => ({ ...s, loop_enabled: p.enabled })); break;
          case 'model': setSnap((s) => ({ ...s, config: { ...s.config, llm_model: p.model } })); break;
          case 'run': setSnap((s) => {
            const runs = [...(s.runs || [])];
            const i = runs.findIndex((r) => r.id === p.id);
            if (i >= 0) runs[i] = p; else runs.push(p);
            return { ...s, runs: runs.slice(-20) };
          }); break;
        }
      };
      es.onerror = () => {
        es?.close(); es = null;
        if (stopped) return;
        setLive(false);
        startPoll();                                   // degrade gracefully to polling
        if (!retryIv) retryIv = setInterval(connect, 15000);
      };
    };

    connect();
    return () => {
      stopped = true;
      es?.close();
      stopPoll();
      if (retryIv) clearInterval(retryIv);
    };
  }, []);

  return { snap, connected, live };
}
