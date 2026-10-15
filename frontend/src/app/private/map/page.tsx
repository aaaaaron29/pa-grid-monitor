import Link from "next/link";
import { PaMap, type ZoneStat } from "@/components/PaMap";
import type { ZoneName } from "@/data/paGeo";
import { ZONES, getZoneSummary } from "@/lib/queries/pjm";

// Private route, gated by src/proxy.ts. This is the only page that hands PJM zone figures
// (Data Miner 2 sourced) to the map. The public /map never does.

export const metadata = { title: "PA map, zone overlay | Grid Watch" };

export default async function PrivateMapPage() {
  const summaries = await Promise.all(ZONES.map((z) => getZoneSummary(z)));
  const zoneStats: Partial<Record<ZoneName, ZoneStat>> = {};
  ZONES.forEach((z, i) => {
    const s = summaries[i];
    zoneStats[z] = {
      currentPrice: s.currentPrice,
      peak24hPrice: s.peak24hPrice,
      anomalies7d: s.anomalies7d,
      freshnessMinutes: s.freshnessSeconds != null ? Math.round(s.freshnessSeconds / 60) : null,
    };
  });

  return (
    <main className="mx-auto w-full max-w-[1100px] px-4 py-12">
      <div className="mb-1 text-[0.8rem] font-semibold" style={{ color: "var(--ink-2)" }}>
        Private: PJM Data Miner 2 sourced
      </div>
      <h1 className="mb-4 text-3xl font-bold">PA map with zone overlay</h1>
      <p className="mb-8 max-w-[680px]" style={{ color: "var(--ink-2)" }}>
        The public map plus the five PJM utility zones, shaded by price or anomaly count. The zone
        shapes are the utilities&apos; service territories, so they approximate PJM&apos;s zones
        rather than reproduce them exactly. Zone figures are private; the same map without them is
        at <Link href="/map">/map</Link>.
      </p>
      <PaMap zoneStats={zoneStats} />
    </main>
  );
}
