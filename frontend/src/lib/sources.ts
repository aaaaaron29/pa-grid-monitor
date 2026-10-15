// One registry for every external source quoted on the site, so a claim is cited the same
// way everywhere and the reference list can never drift from the inline links.
// Nothing here is PJM Data Miner data: these are public reports, filings, and press.

export type SourceKind = "Primary" | "Market data" | "Trade press" | "Local news" | "Skeptic" | "Federal data";

export interface Source {
  id: string;
  kind: SourceKind;
  publisher: string;
  title: string;
  url: string;
  /** What the source is cited for, shown in the reference list. */
  note: string;
}

const list: Source[] = [
  {
    id: "puc-epo",
    kind: "Primary",
    publisher: "PA Public Utility Commission",
    title: "Electric Power Outlook 2024-2029",
    url: "https://www.puc.pa.gov/media/3586/final-draft-2025-epo-2024-2029-8-2025.pdf",
    note: "The regulatory finding that PPL alone faces significant data-center demand growth among PA's utilities.",
  },
  {
    id: "pjm-load-2026",
    kind: "Primary",
    publisher: "PJM",
    title: "2026 Load Forecast Report",
    url: "https://www.pjm.com/-/media/DotCom/library/reports-notices/load-forecast/2026-load-report.pdf",
    note: "PJM's own independent peak-demand forecast revisions.",
  },
  {
    id: "dcd-ppl-pipeline",
    kind: "Trade press",
    publisher: "Data Center Dynamics",
    title: "US utility PPL sees data center pipeline swell by 23% to 25.2GW",
    url: "https://www.datacenterdynamics.com/en/news/us-utility-ppl-sees-data-center-pipeline-swell-by-23-percent-to-252gw/",
    note: "PPL's pipeline growth, from earnings coverage.",
  },
  {
    id: "utilitydive-ppl",
    kind: "Trade press",
    publisher: "Utility Dive",
    title: "PPL data center pipeline, PJM and Blackstone, in earnings coverage",
    url: "https://www.utilitydive.com/news/ppl-data-center-pipeline-pjm-blackstone-earnings/819804/",
    note: "PPL's pipeline growth and the Blackstone joint venture.",
  },
  {
    id: "investing-ppl-q2",
    kind: "Trade press",
    publisher: "Investing.com",
    title: "PPL Q2 2026 investor materials",
    url: "https://www.investing.com/news/company-news/ppl-q2-2026-slides-data-center-growth-drives-23b-capex-plan-93CH-4847201",
    note: "The Q2 2026 pipeline, signed, and under-construction figures.",
  },
  {
    id: "capitalstar-load",
    kind: "Local news",
    publisher: "Pennsylvania Capital-Star",
    title: "Data centers drive higher forecasts for electric demand in PA",
    url: "https://penncapital-star.com/uncategorized/data-centers-drive-higher-forecasts-for-electric-demand-in-pa-sparking-climate-worries/",
    note: "The 2026 to 2034 load trajectory.",
  },
  {
    id: "whyy-peco",
    kind: "Local news",
    publisher: "WHYY",
    title: "PECO data center agreements",
    url: "https://whyy.org/articles/peco-data-centers-agreement/",
    note: "PECO's Transmission Security Agreements.",
  },
  {
    id: "utilitydive-capacity",
    kind: "Market data",
    publisher: "Utility Dive",
    title: "PJM capacity auction and data center demand",
    url: "https://www.utilitydive.com/news/pjm-interconnection-capacity-auction-data-center/808264/",
    note: "The July 2026 capacity auction shortfall.",
  },
  {
    id: "ieefa-capacity",
    kind: "Market data",
    publisher: "IEEFA",
    title: "Projected data center growth spurs PJM capacity prices by a factor of 10",
    url: "https://ieefa.org/resources/projected-data-center-growth-spurs-pjm-capacity-prices-factor-10",
    note: "The July 2026 capacity auction shortfall.",
  },
  {
    id: "lei-report",
    kind: "Skeptic",
    publisher: "London Economics International",
    title: "Uncertainty and Upward Bias Are Inherent in Data Center Electricity Demand Projections",
    url: "https://www.londoneconomics.com/wp-content/uploads/2025/07/LEI-Data-Center-Final-Report-07072025.pdf",
    note: "The duplicate-request, chip-supply, and equipment-bottleneck claims. Prepared for the Southern Environmental Law Center, July 2025.",
  },
  {
    id: "lbnl-llr",
    kind: "Skeptic",
    publisher: "Lawrence Berkeley National Laboratory",
    title: "Large Load Literature Review",
    url: "https://eta-publications.lbl.gov/sites/default/files/2025-10/lbnl_lllreview_sept_update_2025_1.pdf",
    note: "A review of 70+ publications that summarizes the London Economics report, with its duplicate-request and overestimation findings.",
  },
  {
    id: "eia-gridmonitor",
    kind: "Federal data",
    publisher: "U.S. Energy Information Administration",
    title: "Hourly Electric Grid Monitor (EIA-930)",
    url: "https://www.eia.gov/electricity/gridmonitor/",
    note: "Hourly demand, net generation, and interchange for PJM. Published with a lag and revised after the fact.",
  },
];

export const SOURCES: Record<string, Source> = Object.fromEntries(list.map((s) => [s.id, s]));

/** Reference numbers for one page, in the order its author lists the ids (order of first appearance). */
export function numbering(ids: string[]): Record<string, number> {
  const out: Record<string, number> = {};
  ids.forEach((id, i) => {
    if (!SOURCES[id]) throw new Error(`Unknown source id: ${id}`);
    out[id] = i + 1;
  });
  return out;
}
