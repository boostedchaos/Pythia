import { NextResponse } from 'next/server';

/**
 * OSIRIS — NWS active weather alerts as POLYGON zones (api.weather.gov, free, no key).
 * Tornado / severe thunderstorm / flash-flood / flood warning areas, drawn as
 * outlined shaded zones on the map and fed to the oracle. Severity-ranked.
 */
export const dynamic = 'force-dynamic';

const RANK: Record<string, number> = { Extreme: 0, Severe: 1, Moderate: 2, Minor: 3, Unknown: 4 };

export async function GET() {
  const empty = { type: 'FeatureCollection', features: [] as unknown[] };
  try {
    const res = await fetch('https://api.weather.gov/alerts/active?status=actual&message_type=alert', {
      signal: AbortSignal.timeout(12000),
      headers: { 'User-Agent': 'PYTHIA-Oracle (https://localhost)', Accept: 'application/geo+json' },
      cache: 'no-store',
    });
    if (!res.ok) return NextResponse.json({ ...empty, error: `nws ${res.status}` });
    const data = await res.json();

    const feats = (data.features || [])
      .filter((f: any) => f.geometry && (f.geometry.type === 'Polygon' || f.geometry.type === 'MultiPolygon'))
      .map((f: any) => ({
        type: 'Feature',
        geometry: f.geometry,
        properties: {
          event: f.properties?.event || 'Alert',
          severity: f.properties?.severity || 'Unknown',
          headline: f.properties?.headline || '',
          area: f.properties?.areaDesc || '',
        },
      }))
      .sort((a: any, b: any) => (RANK[a.properties.severity] ?? 5) - (RANK[b.properties.severity] ?? 5));

    return NextResponse.json({ type: 'FeatureCollection', features: feats.slice(0, 400), count: feats.length, timestamp: new Date().toISOString() });
  } catch (e) {
    return NextResponse.json({ ...empty, error: String(e) });
  }
}
