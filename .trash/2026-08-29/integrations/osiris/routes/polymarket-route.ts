import { NextResponse } from 'next/server';

/**
 * OSIRIS — Polymarket crowd odds (Gamma API, free, no key).
 * Returns top active binary (Yes/No) markets by volume — real-money crowd
 * probabilities of future events. PYTHIA uses these as forecasting anchors.
 */
export const dynamic = 'force-dynamic';

const SPORTS = /world cup|super bowl|\bnfl\b|\bnba\b|\bnhl\b|\bmlb\b|premier league|la liga|champions league|\bvs\.?\b|\bufc\b|formula 1|grand prix|wimbledon|world series|playoffs|finals mvp|\bopen\b.*(tennis|golf)/i;

export async function GET() {
  try {
    const url = 'https://gamma-api.polymarket.com/markets?active=true&closed=false&limit=150&order=volumeNum&ascending=false';
    const res = await fetch(url, { signal: AbortSignal.timeout(12000), headers: { Accept: 'application/json' }, cache: 'no-store' });
    if (!res.ok) return NextResponse.json({ markets: [], error: `gamma ${res.status}` });
    const data = await res.json();

    const markets: Array<Record<string, unknown>> = [];
    for (const m of Array.isArray(data) ? data : []) {
      let prices: string[] | undefined;
      let outcomes: string[] | undefined;
      try { prices = typeof m.outcomePrices === 'string' ? JSON.parse(m.outcomePrices) : m.outcomePrices; } catch { /* skip */ }
      try { outcomes = typeof m.outcomes === 'string' ? JSON.parse(m.outcomes) : m.outcomes; } catch { /* skip */ }
      if (!prices || !outcomes || outcomes.length !== 2) continue;
      if (String(outcomes[0]).toLowerCase() !== 'yes') continue;     // binary Yes/No only
      const q = String(m.question || '').trim();
      if (!q || SPORTS.test(q)) continue;                            // drop sports noise
      const yes = parseFloat(prices[0]);
      if (Number.isNaN(yes)) continue;
      markets.push({
        id: m.id || m.slug,
        question: q,
        yes_prob: yes,
        volume: Math.round(parseFloat(m.volumeNum || m.volume || '0')),
        end_date: m.endDate || '',
        category: m.category || '',
        url: m.slug ? `https://polymarket.com/market/${m.slug}` : '',
      });
    }
    markets.sort((a, b) => (b.volume as number) - (a.volume as number));
    return NextResponse.json({ markets: markets.slice(0, 30), total: markets.length, timestamp: new Date().toISOString() });
  } catch (e) {
    return NextResponse.json({ markets: [], error: String(e) });
  }
}
