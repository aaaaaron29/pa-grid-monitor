import Link from "next/link";
import {
  getAgeHistory,
  getCompleteness,
  getLatestSnapshot,
  type HealthSnapshot,
} from "@/lib/queries/health";
import { ChartCard, StatsGrid, StatTile } from "@/components/ChartCard";
import { LineChart, ChartLegend } from "@/components/LineChart";
import { SectionRail } from "@/components/SectionRail";

const RAIL = [
  { id: "overview", label: "Is it running" },
  { id: "streams", label: "Data streams" },
  { id: "completeness", label: "Daily completeness" },
  { id: "history", label: "Freshness over time" },
  { id: "website-copy", label: "Website copy" },
  { id: "server", label: "The server" },
  { id: "limits", label: "What this doesn't show" },
];

// The server writes a report after every hourly sync. Past this long without one, a failed
// sync or a dead machine is the likelier explanation than a quiet hour. Matches ops.sh.
const REPORT_LATE_MINUTES = 150;

// Fixed order for the table; the snapshot is JSON and does not keep one.
const STREAM_ORDER = ["pjm_lmp", "pjm_lmp_scored", "eia_demand", "eia_scored", "pjm_load"];

// Axis tops that give round tick labels (0, 1h, 2h, ...) whatever the worst age was.
const AGE_AXIS_TOPS = [60, 120, 240, 480, 960, 1440, 2880, 5760];

type Status = "current" | "late" | "stalled" | "empty";

function fmtDuration(minutes: number) {
  if (minutes < 90) return `${Math.max(0, Math.round(minutes))} min`;
  if (minutes < 60 * 36) return `${(minutes / 60).toFixed(1)} h`;
  return `${(minutes / 1440).toFixed(1)} days`;
}

function fmtUtc(iso: string | null) {
  return iso ? `${iso.slice(0, 16).replace("T", " ")} UTC` : "none";
}

function statusOf(ageMinutes: number | null, limit: number): Status {
  if (ageMinutes === null) return "empty";
  if (ageMinutes > limit) return "stalled";
  if (ageMinutes > limit * 0.6) return "late";
  return "current";
}

const STATUS_STYLE: Record<Status, { word: string; color: string }> = {
  current: { word: "Current", color: "var(--good)" },
  late: { word: "Running late", color: "var(--warning)" },
  stalled: { word: "Stalled", color: "var(--red)" },
  empty: { word: "No data", color: "var(--ink-2)" },
};

function StatusMark({ status }: { status: Status }) {
  const { word, color } = STATUS_STYLE[status];
  return (
    <span className="inline-flex items-center gap-2 font-semibold">
      <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: color }} />
      {word}
    </span>
  );
}

const TH = "border-b px-3.5 py-2.5 text-left text-[0.75rem] font-semibold uppercase tracking-wide";
const TD = "border-b px-3.5 py-2.5";

function Table({ caption, heads, children }: { caption: string; heads: string[]; children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-[10px] border" style={{ borderColor: "var(--border)" }}>
      <table className="w-full min-w-[560px] border-collapse text-[0.9rem]">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {heads.map((h) => (
              <th key={h} scope="col" className={TH} style={{ borderColor: "var(--border)", color: "var(--ink-2)", background: "var(--surface-1)" }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function summarize(snapshot: HealthSnapshot | null, reportAge: number) {
  if (!snapshot) {
    return {
      headline: "The server has not reported yet.",
      detail:
        "It sends a health report after each hourly sync. Until the first one arrives, the completeness chart below still works, because it is counted from the readings themselves.",
    };
  }
  const rows = Object.values(snapshot.streams).map((s) => {
    const live = s.age_minutes === null ? null : s.age_minutes + reportAge;
    return statusOf(live, s.limit_minutes);
  });
  const stalled = rows.filter((r) => r === "stalled").length;
  const late = rows.filter((r) => r === "late").length;
  const total = rows.length;

  if (reportAge > REPORT_LATE_MINUTES) {
    return {
      headline: `No report from the server for ${fmtDuration(reportAge)}.`,
      detail:
        "A report arrives hourly, so either the sync failed or the server is down. What follows is the last known state, aged forward.",
    };
  }
  if (stalled > 0) {
    return {
      headline: `${stalled} of ${total} data streams ${stalled === 1 ? "has" : "have"} stalled.`,
      detail: "See the table below for which, and how long each has gone without a new reading.",
    };
  }
  if (late > 0) {
    return {
      headline: `Running, with ${late} of ${total} streams later than usual.`,
      detail: "Nothing has crossed its alert limit yet.",
    };
  }
  return {
    headline: "Everything is running and current.",
    detail: "Every stream is inside its normal range and the server reported on schedule.",
  };
}

export default async function PipelinePage() {
  const [snapshot, history, completeness] = await Promise.all([
    getLatestSnapshot(),
    getAgeHistory(7),
    getCompleteness(21),
  ]);

  const reportAge = snapshot?.ageMinutes ?? 0;
  const { headline, detail } = summarize(snapshot, reportAge);

  const streams = snapshot
    ? Object.entries(snapshot.streams).sort(
        ([a], [b]) => STREAM_ORDER.indexOf(a) - STREAM_ORDER.indexOf(b),
      )
    : [];
  const onTime = streams.filter(([, s]) => {
    const live = s.age_minutes === null ? null : s.age_minutes + reportAge;
    return statusOf(live, s.limit_minutes) === "current";
  }).length;
  const behind = snapshot
    ? snapshot.sync.reduce((sum, t) => sum + Math.max(0, t.source_count - t.destination_count), 0)
    : null;
  const host = snapshot?.host ?? null;

  const completenessSeries = [
    { key: "prices", color: "var(--blue)", label: "PJM prices present" },
    { key: "scored", color: "var(--orange)", label: "PJM prices scored" },
    { key: "eia", color: "var(--aqua)", label: "EIA demand present" },
    { key: "load", color: "var(--ink-muted)", label: "PJM zone load present" },
  ];
  const worstAge = Math.max(0, ...history.flatMap((h) => [h.pjmPrices ?? 0, h.pjmScored ?? 0]));
  const ageAxis: [number, number] = [
    0,
    AGE_AXIS_TOPS.find((t) => t >= worstAge * 1.05) ?? Math.ceil(worstAge * 1.05),
  ];
  const ageSeries = [
    { key: "pjmPrices", color: "var(--blue)", label: "PJM prices" },
    { key: "pjmScored", color: "var(--orange)", label: "PJM prices, scored" },
  ];

  return (
    <main className="mx-auto w-full max-w-[1100px] px-4 py-12">
      <SectionRail items={RAIL} width="wide" />
      <div className="mb-1 text-[0.8rem] font-semibold" style={{ color: "var(--ink-2)" }}>
        Private: the pipeline behind the pages
      </div>
      <h1 id="overview" className="mb-3 text-3xl font-bold">Pipeline health</h1>
      <p className="mb-1 max-w-[680px] text-[1.05rem] font-semibold">{headline}</p>
      <p className="mb-8 max-w-[680px]" style={{ color: "var(--ink-2)" }}>{detail}</p>

      {snapshot && (
        <StatsGrid cols={3}>
          <StatTile
            label="Last report from the server"
            value={`${fmtDuration(reportAge)} ago`}
            sub={fmtUtc(snapshot.capturedAt)}
          />
          <StatTile
            label="Streams inside normal range"
            value={`${onTime} of ${streams.length}`}
            sub="Five feeds, each with its own limit"
          />
          <StatTile
            label="Rows the website copy is missing"
            value={behind === null ? "--" : behind.toLocaleString("en-US")}
            sub="Server database against Neon"
          />
        </StatsGrid>
      )}

      <h2 id="streams" className="mt-12 mb-3 text-xl font-bold">Data streams</h2>
      {snapshot ? (
        <Table
          caption="How old the newest reading is in each data stream"
          heads={["Stream", "Status", "Age now", "Newest reading", "Normal", "Stalls at"]}
        >
          {streams.map(([key, s]) => {
            const live = s.age_minutes === null ? null : s.age_minutes + reportAge;
            return (
              <tr key={key}>
                <td className={TD} style={{ borderColor: "var(--border)" }}>{s.label}</td>
                <td className={TD} style={{ borderColor: "var(--border)" }}><StatusMark status={statusOf(live, s.limit_minutes)} /></td>
                <td className={`${TD} tabular-nums`} style={{ borderColor: "var(--border)" }}>{live === null ? "--" : fmtDuration(live)}</td>
                <td className={`${TD} tabular-nums`} style={{ borderColor: "var(--border)" }}>{fmtUtc(s.newest)}</td>
                <td className={TD} style={{ borderColor: "var(--border)", color: "var(--ink-2)" }}>{s.normal}</td>
                <td className={`${TD} tabular-nums`} style={{ borderColor: "var(--border)", color: "var(--ink-2)" }}>{fmtDuration(s.limit_minutes)}</td>
              </tr>
            );
          })}
        </Table>
      ) : (
        <p style={{ color: "var(--ink-2)" }}>Nothing to show until the first report arrives.</p>
      )}
      <p className="mt-3 max-w-[680px] text-[0.85rem]" style={{ color: "var(--ink-2)" }}>
        Ages are measured to the newest reading&apos;s own timestamp, as of the last report and
        carried forward to now. A feed that publishes late, like EIA, will always look old. The
        limit is how old it may get before the watchdog raises an alert.
      </p>

      <div id="completeness" className="mt-12">
        <ChartCard
          title="Daily completeness"
          meta="UTC days, last 21"
          legend={<ChartLegend series={completenessSeries} />}
          footnote={
            <>
              Each point is the share of expected readings that exist for that day: 288 five-minute
              intervals in each of 5 zones for prices, 24 hours for EIA demand, and 24 hours in
              each of 5 zones for load. Today counts only the intervals that have already
              happened. The newest day of EIA and the newest two days of load are left out,
              because those feeds publish late, and the scored line starts the day after scoring began. A day that shows a gap but sits within the last
              day or two is usually repaired by the daily heal, which re-pulls PJM&apos;s
              verified feed.
            </>
          }
          expanded={
            <LineChart data={completeness} series={completenessSeries} xKind="day" yFormat="percent" yRange={[0, 100]} fill />
          }
        >
          <LineChart data={completeness} series={completenessSeries} xKind="day" yFormat="percent" yRange={[0, 100]} height={260} />
        </ChartCard>
      </div>

      <div id="history" className="mt-6">
        <ChartCard
          title="Age of the newest PJM price"
          meta="At each hourly report, last 7 days"
          legend={<ChartLegend series={ageSeries} />}
          footnote="Healthy is a few minutes for prices. A climb that does not come back down is an outage, and its height shows how long it lasted. History starts at the first report, so a new deployment begins empty."
          expanded={
            <LineChart data={history} series={ageSeries} yFormat="minutes" yRange={ageAxis} fill emptyMessage="Reports start with the next hourly sync." />
          }
        >
          <LineChart data={history} series={ageSeries} yFormat="minutes" yRange={ageAxis} height={240} emptyMessage="Reports start with the next hourly sync." />
        </ChartCard>
      </div>

      <h2 id="website-copy" className="mt-12 mb-3 text-xl font-bold">Website copy</h2>
      <p className="mb-4 max-w-[680px]" style={{ color: "var(--ink-2)" }}>
        The pipeline writes to the server&apos;s own database, and the hourly sync copies it to
        Neon, which is what these pages read. Equal counts mean the copy is complete.
      </p>
      {snapshot ? (
        <Table
          caption="Row counts on the server and in the website's database, per table"
          heads={["Table", "Server rows", "Website rows", "Missing", "Changed in last sync"]}
        >
          {snapshot.sync.map((t) => {
            const missing = t.source_count - t.destination_count;
            return (
              <tr key={t.table}>
                <td className={TD} style={{ borderColor: "var(--border)" }}><code>{t.table}</code></td>
                <td className={`${TD} tabular-nums`} style={{ borderColor: "var(--border)" }}>{t.source_count.toLocaleString("en-US")}</td>
                <td className={`${TD} tabular-nums`} style={{ borderColor: "var(--border)" }}>{t.destination_count.toLocaleString("en-US")}</td>
                <td className={`${TD} tabular-nums`} style={{ borderColor: "var(--border)", fontWeight: missing > 0 ? 700 : 400 }}>
                  {missing === 0 ? "0" : missing > 0 ? `${missing.toLocaleString("en-US")} behind` : `${Math.abs(missing).toLocaleString("en-US")} extra`}
                </td>
                <td className={`${TD} tabular-nums`} style={{ borderColor: "var(--border)", color: "var(--ink-2)" }}>{t.rows_written.toLocaleString("en-US")}</td>
              </tr>
            );
          })}
        </Table>
      ) : (
        <p style={{ color: "var(--ink-2)" }}>Nothing to show until the first report arrives.</p>
      )}

      <h2 id="server" className="mt-12 mb-3 text-xl font-bold">The server</h2>
      {host ? (
        <dl className="grid max-w-[680px] grid-cols-[minmax(0,1fr)_auto] gap-x-6 gap-y-2.5 text-[0.95rem]">
          <Fact term="Services running" value={`${host.services_running} of ${host.services_expected}`} />
          <Fact term="Failing their health check" value={String(host.services_unhealthy)} />
          <Fact
            term="Open alerts"
            value={host.open_alerts.length === 0 ? "None" : host.open_alerts.join(", ")}
          />
          <Fact term="Last five-minute check" value={host.last_watch_at ? fmtUtc(host.last_watch_at) : "none yet"} />
          <Fact
            term={`Last daily heal (re-pulls ${host.heal_days} days)`}
            value={host.last_heal_at ? fmtUtc(host.last_heal_at) : "has not run yet"}
          />
          <Fact term="Up for" value={`${(host.uptime_seconds / 86400).toFixed(1)} days`} />
          <Fact term="Disk used" value={`${host.disk_used_percent}%`} />
        </dl>
      ) : (
        <p style={{ color: "var(--ink-2)" }}>
          The server did not include its own state in the last report.
        </p>
      )}

      <div id="limits" className="mt-12 max-w-[680px] rounded-lg border p-5" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
        <h3 className="mb-1 font-bold">What this page does not show</h3>
        <p className="mb-0">
          It reports timestamps, counts and states, not prices or loads. It is an hourly picture,
          so an outage shorter than the gap between reports can pass between two of them; the
          completeness chart still records it, since it is counted from the readings. The
          pollers&apos; own error counters and the scoring service&apos;s latency are not
          collected here; they live in the server&apos;s logs. And a green page means the
          pipeline is delivering data, not that the anomaly detector is right.
        </p>
      </div>

      <p className="mt-12">
        <Link href="/private/zones">PJM zone LMP &rarr;</Link>
      </p>
    </main>
  );
}

function Fact({ term, value }: { term: string; value: string }) {
  return (
    <>
      <dt style={{ color: "var(--ink-2)" }}>{term}</dt>
      <dd className="m-0 text-right font-semibold tabular-nums">{value}</dd>
    </>
  );
}
