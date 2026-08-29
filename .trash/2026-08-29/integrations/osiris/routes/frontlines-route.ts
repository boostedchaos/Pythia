import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

/**
 * Ukraine warfront / territory control — DeepStateMap (free, NO API key).
 * Returns occupied + contested territory as clean GeoJSON polygons, with
 * soft-deleted ("dismissed") areas filtered out.
 */
export async function GET() {
  try {
    const res = await fetch('https://deepstatemap.live/api/history/last', {
      signal: AbortSignal.timeout(12000),
      headers: { 'User-Agent': 'Mozilla/5.0 (compatible; OsirisBot/1.0)' },
    });
    if (!res.ok) {
      return NextResponse.json({ type: 'FeatureCollection', features: [], error: 'DeepState unavailable' });
    }
    const data = await res.json();
    const raw: any[] = data?.map?.features || [];
    const features: any[] = [];
    for (const f of raw) {
      if (f?.geometry?.type !== 'Polygon') continue;        // territory areas only
      const name: string = f?.properties?.name || '';
      const code = (name.match(/geoJSON\.status\.(\w+)/)?.[1]) || 'none';
      if (code === 'dismissed' || code === 'dismissed_at') continue;   // soft-deleted
      const status = code === 'occupied' ? 'occupied' : code === 'unknown' ? 'contested' : 'other';
      const label = (name.split('///')[0] || '').trim()
        || (status === 'occupied' ? 'Occupied territory' : status === 'contested' ? 'Contested zone' : 'Frontline area');
      features.push({ type: 'Feature', geometry: f.geometry, properties: { status, label } });
    }
    return NextResponse.json(
      { type: 'FeatureCollection', features, updated: data?.datetime || null, count: features.length },
      { headers: { 'Cache-Control': 'public, s-maxage=1800, stale-while-revalidate=3600' } },
    );
  } catch {
    return NextResponse.json({ type: 'FeatureCollection', features: [], error: 'Failed to fetch frontline data' });
  }
}
