import { SPIKE_PRICE, type FlagSummary } from "@/lib/flagSummary";

function usd(v: number) {
  const abs = Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return (v < 0 ? "-$" : "$") + abs;
}

/** Explains the red dots on the private LMP charts, with this window's own numbers. */
export function FlagInfo({
  zone,
  summary,
  basis,
}: {
  zone: string;
  summary: FlagSummary;
  /** Which chart this sits on: the price itself, or the forecast miss. */
  basis: "price" | "residual";
}) {
  const { flagged, scored, events, onSpike, biggestMiss } = summary;
  const pct = scored > 0 ? (100 * flagged) / scored : 0;
  const mostlySpikes = flagged > 0 && onSpike / flagged >= 0.5;

  return (
    <div className="flex flex-col gap-2.5">
      <h3 className="text-sm font-bold">What the red dots mean</h3>
      <p>
        A red dot marks a 5-minute interval the anomaly detector flagged. It means the price,
        or its miss against the forecast, looked unusual next to the recent past. It does not
        mean the price was wrong.
      </p>
      <p>
        The forecast is the price at the same time one week earlier. An isolation forest scores
        how unusual each interval looks (the forecast miss, the hour and day type, and recent
        movement and volatility), and anything above a fixed score is flagged. That score was
        set on a calm stretch so that about 1% of intervals would flag.
      </p>
      <div>
        <h4 className="mb-1 text-[0.8rem] font-bold">So far in this 7-day window</h4>
        {scored === 0 ? (
          <p>No scored intervals yet for {zone}.</p>
        ) : (
          <p>
            {flagged.toLocaleString("en-US")} of {scored.toLocaleString("en-US")} {zone} intervals (
            {pct.toFixed(1)}%) are flagged, in {events} separate {events === 1 ? "event" : "events"}
            . Flags less than an hour apart count as one event.
            {basis === "price" && flagged > 0 && (
              <>
                {" "}
                {onSpike} of them sit on prices beyond {usd(SPIKE_PRICE)} in either direction.
              </>
            )}
            {basis === "residual" && biggestMiss && (
              <>
                {" "}
                The largest flagged miss is {usd(biggestMiss.value)} at{" "}
                {biggestMiss.t.slice(5, 16).replace("T", " ")}.
              </>
            )}
          </p>
        )}
      </div>
      <p>
        {mostlySpikes
          ? "Most flags land on prices that were themselves extreme, in short volatile stretches. That points to unusual market conditions, not faults in the data."
          : "Flags cluster in short stretches, so a few volatile days can push the share past 1% without anything being broken."}{" "}
        A spike can be flagged again a week later, because the forecast replays it. With no
        labeled anomalies to score against, treat a flag as worth a look.
      </p>
    </div>
  );
}
