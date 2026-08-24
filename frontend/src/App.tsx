import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { motion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";

import { Button } from "./components/ui/button";
import { cn } from "./lib/utils";

type AnyRecord = Record<string, any>;

type Payload = {
  rows?: AnyRecord[];
  latest?: AnyRecord;
  fetchedAt?: string;
  lastError?: string | null;
};

type Metric = {
  label: string;
  value?: string;
  meta?: string;
  note?: string;
  path: string;
  toneValue?: number | null;
};

type Section = {
  id: string;
  title: string;
  subtitle: string;
  metrics: Metric[];
};

const videoUrl =
  "https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260428_193507_4286c423-2fd9-4efd-92bd-91a939453fc1.mp4";

const identityLabels: Record<string, string> = {
  foreign: "外資",
  investmentTrust: "投信",
  dealer: "自營",
};

const navTabs = [
  { label: "現貨", href: "#spot" },
  { label: "期貨與大額", href: "#futures" },
  { label: "選擇權", href: "#options" },
];

function getValue(source: AnyRecord | undefined, path: string, fallback?: any) {
  if (!source) return fallback;
  return (
    path.split(".").reduce<any>((value, key) => {
      if (value == null) return undefined;
      return value[key];
    }, source) ?? fallback
  );
}

function toNumber(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value.replace(/[,%億+]/g, ""));
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return 0;
}

function text(value: unknown, fallback = "-") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function toneClass(value: unknown) {
  const number = toNumber(value);
  if (number < 0) return "text-rivr-red";
  if (number > 0) return "text-rivr-ink";
  return "text-rivr-muted";
}

function toneSoftClass(value: unknown) {
  const number = toNumber(value);
  if (number < 0) return "border-rivr-red/20 bg-red-50/70";
  if (number > 0) return "border-rivr-ink/10 bg-white/55";
  return "border-rivr-ink/10 bg-white/35";
}

function directionIcon(value: unknown) {
  const number = toNumber(value);
  if (number < 0) return <ArrowDownRight className="h-4 w-4 text-rivr-red" />;
  if (number > 0) return <ArrowUpRight className="h-4 w-4 text-rivr-ink" />;
  return <Activity className="h-4 w-4 text-rivr-muted" />;
}

function chronologicalRows(rows: AnyRecord[]) {
  return [...rows].slice(0, 30).reverse();
}

function Sparkline({ rows, path, toneValue }: { rows: AnyRecord[]; path: string; toneValue?: number | null }) {
  const points = useMemo(() => {
    const values = chronologicalRows(rows).map((row) => toNumber(getValue(row, path, 0)));
    if (values.length < 2) return "";
    let min = Math.min(...values);
    let max = Math.max(...values);
    if (min === max) {
      min -= 1;
      max += 1;
    }
    return values
      .map((value, index) => {
        const x = (index / Math.max(values.length - 1, 1)) * 100;
        const y = 36 - ((value - min) / (max - min)) * 30;
        return `${x.toFixed(2)},${y.toFixed(2)}`;
      })
      .join(" ");
  }, [path, rows]);

  return (
    <svg className="h-12 w-full overflow-visible" viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true">
      <polyline
        points={points}
        fill="none"
        stroke={toNumber(toneValue) < 0 ? "#d92d20" : "#1e325a"}
        strokeWidth="1.8"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

function BarTrend({ rows, title, path }: { rows: AnyRecord[]; title: string; path: string }) {
  const values = useMemo(() => chronologicalRows(rows).map((row) => toNumber(getValue(row, path, 0))), [path, rows]);
  const maxAbs = Math.max(...values.map((value) => Math.abs(value)), 1);

  return (
    <div className="rivr-panel p-4 md:p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-rivr-ink">{title}</div>
          <div className="text-xs text-rivr-muted">近 30 個交易日</div>
        </div>
        <BarChart3 className="h-4 w-4 text-rivr-muted" />
      </div>
      <div className="relative flex h-32 items-center gap-1 rounded-[1.4rem] border border-rivr-ink/10 bg-white/45 px-3 py-4">
        <div className="absolute left-3 right-3 top-1/2 h-px bg-rivr-ink/10" />
        {values.map((value, index) => {
          const height = Math.max(2, (Math.abs(value) / maxAbs) * 52);
          const positive = value >= 0;
          return (
            <div key={`${path}-${index}`} className="relative z-10 flex h-full flex-1 items-center">
              <div
                className={cn("w-full rounded-full", positive ? "self-start bg-rivr-ink" : "self-end bg-rivr-red", value === 0 ? "bg-slate-300" : "")}
                style={{ height }}
                title={`${value}`}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

function formatCompact(value: number) {
  const abs = Math.abs(value);
  if (abs >= 1000000) return `${(value / 1000000).toFixed(1)}m`;
  if (abs >= 1000) return `${Math.round(value / 1000)}k`;
  return `${Math.round(value)}`;
}

function formatDateLabel(value: string | undefined) {
  if (!value) return "";
  const parts = value.split("-");
  if (parts.length >= 3) return `${parts[1]}/${parts[2]}`;
  return value;
}

function OptionCompositeChart({
  rows,
  title,
  subtitle,
  longPath,
  shortPath,
  netPath,
}: {
  rows: AnyRecord[];
  title: string;
  subtitle: string;
  longPath: string;
  shortPath: string;
  netPath: string;
}) {
  const data = useMemo(
    () =>
      chronologicalRows(rows).map((row) => ({
        date: row.dateLabel || row.date,
        longValue: toNumber(getValue(row, longPath, 0)),
        shortValue: toNumber(getValue(row, shortPath, 0)),
        netValue: toNumber(getValue(row, netPath, 0)),
      })),
    [longPath, netPath, rows, shortPath],
  );

  const width = 760;
  const height = 280;
  const padding = { top: 36, right: 46, bottom: 42, left: 46 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const centerY = padding.top + chartHeight / 2;
  const lineMax = Math.max(...data.flatMap((item) => [item.longValue, item.shortValue]), 1);
  const netMax = Math.max(...data.map((item) => Math.abs(item.netValue)), 1);
  const barWidth = Math.max(6, Math.min(16, chartWidth / Math.max(data.length, 1) - 5));

  const xForIndex = (index: number) => padding.left + (data.length <= 1 ? chartWidth / 2 : (index / (data.length - 1)) * chartWidth);
  const yForLine = (value: number) => padding.top + (1 - value / lineMax) * chartHeight;
  const barHeight = (value: number) => (Math.abs(value) / netMax) * (chartHeight / 2 - 10);
  const linePath = (key: "longValue" | "shortValue") =>
    data
      .map((item, index) => `${index === 0 ? "M" : "L"} ${xForIndex(index).toFixed(2)} ${yForLine(item[key]).toFixed(2)}`)
      .join(" ");
  const dateTicks = data.filter((_, index) => index === 0 || index === Math.floor(data.length / 2) || index === data.length - 1);

  return (
    <div className="rivr-panel p-4 md:p-5">
      <div className="mb-3 text-center">
        <div className="text-base font-semibold text-rivr-ink">{title}</div>
        <div className="text-xs text-rivr-muted">{subtitle}</div>
      </div>
      <svg className="h-[280px] w-full overflow-visible" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
        {[0, 0.5, 1].map((ratio) => {
          const y = padding.top + ratio * chartHeight;
          return <line key={ratio} x1={padding.left} x2={width - padding.right} y1={y} y2={y} stroke="rgba(30,50,90,0.10)" strokeWidth="1" />;
        })}
        <line x1={padding.left} x2={width - padding.right} y1={centerY} y2={centerY} stroke="rgba(30,50,90,0.20)" strokeWidth="1.2" />

        <text x={padding.left - 8} y={padding.top + 4} textAnchor="end" className="fill-rivr-muted text-[12px]">
          {formatCompact(lineMax)}
        </text>
        <text x={padding.left - 8} y={centerY + 4} textAnchor="end" className="fill-rivr-muted text-[12px]">
          {formatCompact(lineMax / 2)}
        </text>
        <text x={width - padding.right + 8} y={padding.top + 4} textAnchor="start" className="fill-rivr-muted text-[12px]">
          {formatCompact(netMax)}
        </text>
        <text x={width - padding.right + 8} y={centerY + 4} textAnchor="start" className="fill-rivr-muted text-[12px]">
          0
        </text>
        <text x={width - padding.right + 8} y={height - padding.bottom + 4} textAnchor="start" className="fill-rivr-muted text-[12px]">
          -{formatCompact(netMax)}
        </text>

        {data.map((item, index) => {
          const x = xForIndex(index) - barWidth / 2;
          const h = Math.max(1, barHeight(item.netValue));
          const y = item.netValue >= 0 ? centerY - h : centerY;
          return (
            <rect
              key={`${item.date}-${index}`}
              x={x}
              y={y}
              width={barWidth}
              height={h}
              rx="2"
              fill={item.netValue >= 0 ? "rgba(30,50,90,0.24)" : "rgba(217,45,32,0.24)"}
            />
          );
        })}

        <path d={linePath("longValue")} fill="none" stroke="#ff3333" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
        <path d={linePath("shortValue")} fill="none" stroke="#1ba80f" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />

        {dateTicks.map((item) => (
          <text key={item.date} x={xForIndex(data.indexOf(item))} y={height - 16} textAnchor="middle" className="fill-rivr-muted text-[12px]">
            {formatDateLabel(item.date)}
          </text>
        ))}
      </svg>
      <div className="mt-2 flex flex-wrap items-center justify-center gap-5 text-xs text-rivr-muted">
        <span className="inline-flex items-center gap-2">
          <span className="h-0.5 w-6 rounded-full bg-[#ff3333]" />
          合成多單
        </span>
        <span className="inline-flex items-center gap-2">
          <span className="h-0.5 w-6 rounded-full bg-[#1ba80f]" />
          合成空單
        </span>
        <span className="inline-flex items-center gap-2">
          <span className="h-3 w-3 rounded-sm bg-rivr-ink/25" />
          多空淨額
        </span>
      </div>
    </div>
  );
}

function MetricCard({ metric, rows }: { metric: Metric; rows: AnyRecord[] }) {
  return (
    <div className={cn("rivr-panel p-4 transition-transform duration-200 hover:-translate-y-0.5", toneSoftClass(metric.toneValue))}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="text-sm font-medium text-rivr-muted">{metric.label}</div>
        <div className="rounded-full bg-white/60 p-2 shadow-sm">{directionIcon(metric.toneValue)}</div>
      </div>
      <div className={cn("text-2xl font-semibold tracking-tight", toneClass(metric.toneValue))}>{text(metric.value)}</div>
      <div className="mt-2 min-h-5 text-xs text-rivr-muted">{text(metric.meta, "")}</div>
      {metric.note ? <div className="mt-3 rounded-[1rem] border border-rivr-ink/10 bg-white/45 p-3 text-xs leading-5 text-rivr-muted">{metric.note}</div> : null}
      <div className="mt-4">
        <Sparkline rows={rows} path={metric.path} toneValue={metric.toneValue} />
      </div>
    </div>
  );
}

function buildSections(row: AnyRecord): Section[] {
  const cash = row.cashMarket || {};
  const spot = row.spotInstitutional || {};
  const futures = row.futuresInstitutional || {};
  const large = row.largeTraderFutures || {};
  const pcr = row.optionPcr || {};
  const foreignOpt = row.foreignOptionAmount || {};
  const institutionalOpt = row.optionInstitutionalAmount || {};
  const dealerOpt = institutionalOpt.dealer || {};
  const txo = row.txoInstitutionalOpenInterest || {};
  const dealerOptionView = row.optionPositionViews?.dealer || {};
  const foreignView = row.foreignPositionView || {};
  const retail = row.retailMiniFutures || {};

  return [
    {
      id: "foreign-view",
      title: "外資操作判讀",
      subtitle: "整合外資現貨、期貨大戶、PCR 與選擇權，判斷偏多、偏空或對沖。",
      metrics: [
        {
          label: "今日判讀",
          value: foreignView.label || "中性 / 訊號不足",
          meta: foreignView.reason || foreignView.summary || "-",
          note: foreignView.explanation || "",
          path: "foreignPositionView.score",
          toneValue: foreignView.score,
        },
      ],
    },
    {
      id: "spot",
      title: "現貨",
      subtitle: "成交金額與三大法人買賣超，單位皆為億元。",
      metrics: [
        {
          label: "成交金額",
          value: cash.listedAmountYiFormat,
          meta: cash.listedAmountDiffFormat ? `較前日 ${cash.listedAmountDiffFormat}` : "上市成交金額",
          path: "cashMarket.listedAmount",
          toneValue: 0,
        },
        {
          label: "外資買賣超",
          value: spot.foreignNetBuyAmountYiFormat,
          meta: spot.foreignNetBuyAmountDiffFormat ? `較前日 ${spot.foreignNetBuyAmountDiffFormat}` : "",
          path: "spotInstitutional.foreignNetBuyAmount",
          toneValue: spot.foreignNetBuyAmount,
        },
        {
          label: "投信買賣超",
          value: spot.investmentTrustNetBuyAmountYiFormat,
          meta: spot.investmentTrustNetBuyAmountDiffFormat ? `較前日 ${spot.investmentTrustNetBuyAmountDiffFormat}` : "",
          path: "spotInstitutional.investmentTrustNetBuyAmount",
          toneValue: spot.investmentTrustNetBuyAmount,
        },
        {
          label: "自營買賣超",
          value: spot.dealerNetBuyAmountYiFormat,
          meta: spot.dealerNetBuyAmountDiffFormat ? `較前日 ${spot.dealerNetBuyAmountDiffFormat}` : "",
          path: "spotInstitutional.dealerNetBuyAmount",
          toneValue: spot.dealerNetBuyAmount,
        },
      ],
    },
    {
      id: "futures",
      title: "期貨與大額交易人",
      subtitle: "臺股期貨組合與 TX+MTX/4+TMF/20 所有契約大額留倉。",
      metrics: [
        ...["foreign", "investmentTrust", "dealer"].map((id) => {
          const item = futures[id] || {};
          return {
            label: `${identityLabels[id]}期貨淨額`,
            value: item.netFormat,
            meta: `多 ${item.longFormat || "-"} / 空 ${item.shortFormat || "-"}`,
            path: `futuresInstitutional.${id}.net`,
            toneValue: item.net,
          };
        }),
        {
          label: "前五大淨值",
          value: large.top5NetFormat,
          meta: `買方 ${large.top5LongFormat || "-"} (${large.top5LongPercentFormat || "-"}) / 賣方 ${large.top5ShortFormat || "-"} (${large.top5ShortPercentFormat || "-"})`,
          path: "largeTraderFutures.top5Net",
          toneValue: large.top5Net,
        },
        {
          label: "前十大淨值",
          value: large.top10NetFormat,
          meta: `買方 ${large.top10LongFormat || "-"} (${large.top10LongPercentFormat || "-"}) / 賣方 ${large.top10ShortFormat || "-"} (${large.top10ShortPercentFormat || "-"})`,
          path: "largeTraderFutures.top10Net",
          toneValue: large.top10Net,
        },
      ],
    },
    {
      id: "options",
      title: "選擇權",
      subtitle: "未平倉 PCR、小台指散戶多空比、外資與自營商選擇權金額及法人未平倉。",
      metrics: [
        {
          label: "未平倉 PCR",
          value: pcr.openInterestPcrFormat,
          meta: `成交量 PCR ${pcr.volumePcrFormat || "-"}`,
          path: "optionPcr.openInterestPcr",
          toneValue: toNumber(pcr.openInterestPcr) - 100,
        },
        {
          label: "小台指散戶多空比",
          value: retail.retailLongShortRatioFormat,
          meta: `散戶留倉 ${retail.retailPositionFormat || "-"} / 全體未平倉 ${retail.totalOpenInterestFormat || "-"}`,
          path: "retailMiniFutures.retailLongShortRatio",
          toneValue: retail.retailLongShortRatio,
        },
        {
          label: "外資選擇權金額",
          value: foreignOpt.netAmountFormat,
          meta: `多 ${foreignOpt.bullAmountFormat || "-"} / 空 ${foreignOpt.bearAmountFormat || "-"}`,
          path: "foreignOptionAmount.netAmount",
          toneValue: foreignOpt.netAmount,
        },
        {
          label: "外資選擇權淨額",
          value: txo.foreign?.netLotFormat,
          meta: `多 ${txo.foreign?.bullLotFormat || "-"} / 空 ${txo.foreign?.bearLotFormat || "-"}`,
          path: "txoInstitutionalOpenInterest.foreign.netLot",
          toneValue: txo.foreign?.netLot,
        },
        {
          label: "投信選擇權淨額",
          value: txo.investmentTrust?.netLotFormat,
          meta: `多 ${txo.investmentTrust?.bullLotFormat || "-"} / 空 ${txo.investmentTrust?.bearLotFormat || "-"}`,
          path: "txoInstitutionalOpenInterest.investmentTrust.netLot",
          toneValue: txo.investmentTrust?.netLot,
        },
        {
          label: "自營商選擇權判讀",
          value: dealerOptionView.label,
          meta: dealerOptionView.reason || "更新資料後顯示自營商金額與口數判讀",
          path: "optionPositionViews.dealer.score",
          toneValue: dealerOptionView.score,
        },
        {
          label: "自營商選擇權金額",
          value: dealerOpt.netAmountFormat,
          meta: `多 ${dealerOpt.bullAmountFormat || "-"} / 空 ${dealerOpt.bearAmountFormat || "-"}`,
          path: "optionInstitutionalAmount.dealer.netAmount",
          toneValue: dealerOpt.netAmount,
        },
        {
          label: "自營商選擇權淨額",
          value: txo.dealer?.netLotFormat,
          meta: `多 ${txo.dealer?.bullLotFormat || "-"} / 空 ${txo.dealer?.bearLotFormat || "-"}`,
          path: "txoInstitutionalOpenInterest.dealer.netLot",
          toneValue: txo.dealer?.netLot,
        },
      ],
    },
  ];
}

function HeroBadge() {
  return (
    <motion.div
      className="mx-auto mb-3 flex w-fit items-center gap-2 rounded-full border border-white/30 bg-white/65 px-4 py-2 text-[14px] font-normal text-rivr-ink backdrop-blur-md"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, ease: "easeOut" }}
    >
      <Sparkles className="h-4 w-4 text-rivr-ink" />
      <span>TWSE / TAIFEX 籌碼總覽</span>
    </motion.div>
  );
}

function SummaryHero({ payload }: { payload: Payload }) {
  const row = payload.latest || {};
  const market = row.marketIndex || {};
  const cash = row.cashMarket || {};
  const view = row.foreignPositionView || {};

  const cells = [
    { label: "日期", value: row.dateLabel || "-", meta: payload.fetchedAt ? `更新 ${payload.fetchedAt}` : "尚未更新", tone: 0 },
    { label: "大盤指數", value: market.taiexCloseFormat || "-", meta: "發行量加權股價指數", tone: market.taiexChange },
    { label: "漲跌點數", value: market.taiexChangeFormat || "-", meta: "當日漲跌", tone: market.taiexChange },
    { label: "漲跌百分比", value: market.taiexChangePercentFormat || "-", meta: "當日漲跌幅", tone: market.taiexChangePercent },
    { label: "成交金額", value: cash.listedAmountYiFormat || "-", meta: "上市現貨，億元", tone: 0 },
  ];

  return (
    <section className="relative min-h-[720px] overflow-hidden rounded-[1.5rem] bg-white/10 shadow-none md:rounded-[3rem]">
      <video
        className="absolute inset-0 z-0 h-full w-full object-cover object-[65%] opacity-90 lg:object-center"
        src={videoUrl}
        autoPlay
        muted
        loop
        playsInline
        aria-hidden="true"
      />
      <div className="absolute inset-0 z-0 bg-[linear-gradient(180deg,rgba(240,240,240,0.18),rgba(240,240,240,0.84)_55%,rgba(240,240,240,0.98))]" />

      <div className="relative z-10 flex min-h-[720px] flex-col">
        <nav className="flex w-full flex-wrap items-center justify-between gap-4 px-6 py-6 md:px-10">
          <div className="flex items-center gap-3">
            <img src="/assets/logo.png" alt="" className="h-9 w-9 object-contain" />
            <div>
              <div className="text-xl font-semibold tracking-tight text-rivr-ink">市場數據</div>
              <div className="text-xs text-rivr-muted">Daily Market Intelligence</div>
            </div>
          </div>
          <div className="order-3 flex w-full justify-center gap-2 md:order-none md:w-auto">
            {navTabs.map((tab) => (
              <a
                key={tab.href}
                href={tab.href}
                className="rounded-full border border-white/55 bg-white/45 px-4 py-2 text-sm font-semibold text-rivr-ink shadow-[0_12px_35px_rgba(30,50,90,0.10)] backdrop-blur-xl transition hover:bg-white/70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rivr-ink/50"
              >
                {tab.label}
              </a>
            ))}
          </div>
          <div className="hidden text-sm font-normal text-rivr-muted md:block">TWSE / TAIFEX official data</div>
        </nav>

        <div className="flex flex-1 flex-col items-center px-5 pb-6 pt-3 text-center md:px-8">
          <HeroBadge />
          <motion.h1
            className="mb-3 max-w-5xl text-4xl font-normal leading-[1.05] tracking-tight text-rivr-muted sm:text-5xl md:text-6xl lg:text-[80px]"
            initial={{ opacity: 0, scale: 0.98 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.8, delay: 0.2 }}
          >
            市場數據，維持在一個
            <span className="block text-rivr-ink">清楚的視野。</span>
          </motion.h1>
          <div className="mt-8 grid w-full gap-3 md:grid-cols-5">
            {cells.map((cell) => (
              <div key={cell.label} className="rounded-[1.4rem] border border-white/40 bg-white/45 p-4 text-left shadow-[0_18px_70px_rgba(30,50,90,0.10)] backdrop-blur-xl">
                <div className="text-xs font-medium uppercase tracking-[0.12em] text-rivr-muted">{cell.label}</div>
                <div className={cn("mt-2 text-2xl font-semibold tracking-tight", toneClass(cell.tone))}>{cell.value}</div>
                <div className="mt-2 text-xs text-rivr-muted">{cell.meta}</div>
              </div>
            ))}
          </div>

          <motion.div
            className="mt-auto grid w-full gap-4 pt-8 lg:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.3 }}
          >
            <div className="rivr-panel p-5 text-left">
              <div className="mb-3 flex items-center justify-between">
                <div className="text-sm font-semibold text-rivr-muted">外資操作判讀</div>
                <ShieldCheck className="h-4 w-4 text-rivr-muted" />
              </div>
              <div className={cn("text-3xl font-semibold", toneClass(view.score))}>{view.label || "中性 / 訊號不足"}</div>
              <div className="mt-3 text-sm leading-6 text-rivr-muted">{view.reason || view.summary || "尚無判讀資料"}</div>
              <div className="mt-4 rounded-[1rem] border border-rivr-ink/10 bg-white/45 p-3 text-xs leading-5 text-rivr-muted">
                {view.explanation || "多空強度與避險說明會在資料更新後顯示。"}
              </div>
            </div>

            <div className="grid gap-3 rounded-[1.5rem] bg-white/25 p-3 backdrop-blur-xl md:grid-cols-3">
              {["foreign", "investmentTrust", "dealer"].map((id) => {
                const item = row.futuresInstitutional?.[id] || {};
                return (
                  <div key={id} className="rounded-[1.2rem] bg-white/50 p-4 text-left">
                    <div className="text-xs text-rivr-muted">{identityLabels[id]}期貨淨額</div>
                    <div className={cn("mt-2 text-2xl font-semibold leading-tight md:text-[30px]", toneClass(item.net))}>
                      {item.netFormat || "-"}
                    </div>
                    <div className="mt-1 text-sm leading-snug text-rivr-muted md:text-[18px]">
                      多 {item.longFormat || "-"} / 空 {item.shortFormat || "-"}
                    </div>
                  </div>
                );
              })}
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  );
}

function ActionPanel({
  payload,
  onRefresh,
  onSendDiscord,
  busy,
  notice,
}: {
  payload: Payload;
  onRefresh: () => Promise<void>;
  onSendDiscord: () => Promise<void>;
  busy: "refresh" | "discord" | null;
  notice: { message: string; tone: "neutral" | "positive" | "negative" };
}) {
  return (
    <section className="rivr-panel p-4 md:p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-rivr-ink">資料與 Discord 操作</h2>
          <p className="mt-1 text-sm text-rivr-muted">
            目前資料日期 {payload.latest?.dateLabel || "-"}，共有 {payload.rows?.length || 0} 筆交易日資料。
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button
            type="button"
            variant="ghost"
            className="rounded-full border border-rivr-ink/10 bg-white/55 px-5 text-rivr-ink hover:bg-white/80"
            disabled={busy !== null}
            onClick={onRefresh}
          >
            <RefreshCw className={cn("mr-2 h-4 w-4", busy === "refresh" ? "animate-spin" : "")} />
            更新資料
          </Button>
          <Button
            type="button"
            className="rounded-full bg-rivr-ink px-5 text-white hover:bg-rivr-ink/90"
            disabled={busy !== null}
            onClick={onSendDiscord}
          >
            <Send className="mr-2 h-4 w-4" />
            傳送 Discord
          </Button>
        </div>
      </div>
      <div
        className={cn(
          "mt-4 rounded-[1rem] border px-4 py-3 text-sm",
          notice.tone === "positive" ? "border-rivr-ink/10 bg-white/55 text-rivr-ink" : "",
          notice.tone === "negative" ? "border-rivr-red/25 bg-red-50/80 text-rivr-red" : "",
          notice.tone === "neutral" ? "border-rivr-ink/10 bg-white/35 text-rivr-muted" : "",
        )}
      >
        {notice.message}
      </div>
    </section>
  );
}

function DashboardSections({ rows, latest }: { rows: AnyRecord[]; latest: AnyRecord }) {
  const sections = useMemo(() => buildSections(latest), [latest]);

  return (
    <div className="space-y-8">
      {sections.map((section) => (
        <section id={section.id} key={section.id} className="scroll-mt-6 space-y-4">
          <div>
            <h2 className="text-xl font-semibold tracking-tight text-rivr-ink">{section.title}</h2>
            <p className="mt-1 text-sm text-rivr-muted">{section.subtitle}</p>
          </div>
          <div className={cn("grid gap-4", section.id === "foreign-view" ? "grid-cols-1" : "md:grid-cols-2 xl:grid-cols-4")}>
            {section.metrics.map((metric) => (
              <MetricCard key={`${section.title}-${metric.label}`} metric={metric} rows={rows} />
            ))}
          </div>
        </section>
      ))}

      <section className="grid gap-4 xl:grid-cols-2">
        <OptionCompositeChart
          rows={rows}
          title="外資選擇權合成部位（口數）"
          subtitle="多方口數 / 空方口數 / 多空淨額"
          longPath="txoInstitutionalOpenInterest.foreign.bullLot"
          shortPath="txoInstitutionalOpenInterest.foreign.bearLot"
          netPath="txoInstitutionalOpenInterest.foreign.netLot"
        />
        <OptionCompositeChart
          rows={rows}
          title="外資選擇權合成部位（金額）"
          subtitle="多方金額 / 空方金額 / 多空淨額"
          longPath="foreignOptionAmount.bullAmount"
          shortPath="foreignOptionAmount.bearAmount"
          netPath="foreignOptionAmount.netAmount"
        />
        <OptionCompositeChart
          rows={rows}
          title="自營商選擇權合成部位（口數）"
          subtitle="多方口數 / 空方口數 / 多空淨額"
          longPath="txoInstitutionalOpenInterest.dealer.bullLot"
          shortPath="txoInstitutionalOpenInterest.dealer.bearLot"
          netPath="txoInstitutionalOpenInterest.dealer.netLot"
        />
        <OptionCompositeChart
          rows={rows}
          title="自營商選擇權合成部位（金額）"
          subtitle="多方金額 / 空方金額 / 多空淨額"
          longPath="optionInstitutionalAmount.dealer.bullAmount"
          shortPath="optionInstitutionalAmount.dealer.bearAmount"
          netPath="optionInstitutionalAmount.dealer.netAmount"
        />
      </section>
    </div>
  );
}

function HistoryTable({ rows }: { rows: AnyRecord[] }) {
  return (
    <section id="history" className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold tracking-tight text-rivr-ink">近 30 日明細</h2>
        <p className="mt-1 text-sm text-rivr-muted">PCR 使用未平倉 PCR；正值偏多顯示深藍黑色，負值偏空顯示紅色。</p>
      </div>
      <div className="rivr-panel overflow-hidden p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1280px] border-collapse text-left text-sm">
            <thead className="bg-white/45 text-xs text-rivr-muted">
              <tr>
                {[
                  "日期",
                  "外資操作判讀",
                  "大盤",
                  "漲跌",
                  "漲跌%",
                  "成交金額",
                  "外資買賣超",
                  "投信買賣超",
                  "自營買賣超",
                  "外資期貨淨額",
                  "前五大淨值",
                  "前十大淨值",
                  "PCR",
                  "小台指散戶多空比",
                  "外資選擇權金額",
                  "外資選擇權淨額",
                  "自營商選擇權金額",
                  "自營商選擇權淨額",
                ].map((header) => (
                  <th key={header} className="whitespace-nowrap border-b border-rivr-ink/10 px-4 py-3 font-semibold">
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const m = row.marketIndex || {};
                const cash = row.cashMarket || {};
                const spot = row.spotInstitutional || {};
                const fut = row.futuresInstitutional?.foreign || {};
                const large = row.largeTraderFutures || {};
                const pcr = row.optionPcr || {};
                const retail = row.retailMiniFutures || {};
                const opt = row.foreignOptionAmount || {};
                const txo = row.txoInstitutionalOpenInterest?.foreign || {};
                const dealerOpt = row.optionInstitutionalAmount?.dealer || {};
                const dealerTxo = row.txoInstitutionalOpenInterest?.dealer || {};
                const view = row.foreignPositionView || {};
                const cells = [
                  { value: row.dateLabel || "-" },
                  { value: view.label || "-", tone: view.score },
                  { value: m.taiexCloseFormat || "-" },
                  { value: m.taiexChangeFormat || "-", tone: m.taiexChange },
                  { value: m.taiexChangePercentFormat || "-", tone: m.taiexChangePercent },
                  { value: cash.listedAmountYiFormat || "-" },
                  { value: spot.foreignNetBuyAmountYiFormat || "-", tone: spot.foreignNetBuyAmount },
                  { value: spot.investmentTrustNetBuyAmountYiFormat || "-", tone: spot.investmentTrustNetBuyAmount },
                  { value: spot.dealerNetBuyAmountYiFormat || "-", tone: spot.dealerNetBuyAmount },
                  { value: fut.netFormat || "-", tone: fut.net },
                  { value: large.top5NetFormat || "-", tone: large.top5Net },
                  { value: large.top10NetFormat || "-", tone: large.top10Net },
                  { value: pcr.openInterestPcrFormat || "-" },
                  { value: retail.retailLongShortRatioFormat || "-", tone: retail.retailLongShortRatio },
                  { value: opt.netAmountFormat || "-", tone: opt.netAmount },
                  { value: txo.netLotFormat || "-", tone: txo.netLot },
                  { value: dealerOpt.netAmountFormat || "-", tone: dealerOpt.netAmount },
                  { value: dealerTxo.netLotFormat || "-", tone: dealerTxo.netLot },
                ];
                return (
                  <tr key={row.date || row.dateLabel} className="border-b border-rivr-ink/5 transition-colors hover:bg-white/45">
                    {cells.map((cell, index) => (
                      <td key={`${row.date}-${index}`} className={cn("whitespace-nowrap px-4 py-3 text-rivr-ink/80", cell.tone !== undefined ? toneClass(cell.tone) : "")}>
                        {cell.value}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function App() {
  const [payload, setPayload] = useState<Payload>({});
  const [busy, setBusy] = useState<"refresh" | "discord" | null>(null);
  const [notice, setNotice] = useState<{ message: string; tone: "neutral" | "positive" | "negative" }>({
    message: "正在載入每日籌碼資料。",
    tone: "neutral",
  });

  async function loadData() {
    const response = await fetch("/api/data");
    const data = (await response.json()) as Payload;
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    setPayload(data);
    setNotice({
      message: `資料已載入：${data.latest?.dateLabel || "-"}，近 ${data.rows?.length || 0} 個交易日。${data.lastError ? ` 上次更新錯誤：${data.lastError}` : ""}`,
      tone: data.lastError ? "negative" : "neutral",
    });
  }

  async function refreshData() {
    setBusy("refresh");
    setNotice({ message: "正在更新 TWSE / TAIFEX 資料，這可能需要一點時間。", tone: "neutral" });
    try {
      const response = await fetch("/api/refresh", { method: "POST" });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
      await loadData();
      setNotice({ message: `更新完成：${data.latest?.dateLabel || payload.latest?.dateLabel || "-"}`, tone: "positive" });
    } catch (error) {
      setNotice({ message: `更新失敗：${error instanceof Error ? error.message : String(error)}`, tone: "negative" });
    } finally {
      setBusy(null);
    }
  }

  async function sendDiscord() {
    setBusy("discord");
    setNotice({ message: "正在傳送 Discord 外資操作判讀與近 15 日明細圖片。", tone: "neutral" });
    try {
      const response = await fetch("/api/send-discord", { method: "POST" });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
      setNotice({ message: "Discord 已送出。", tone: "positive" });
    } catch (error) {
      setNotice({ message: `Discord 傳送失敗：${error instanceof Error ? error.message : String(error)}`, tone: "negative" });
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    loadData().catch((error) => {
      setNotice({ message: `載入資料失敗：${error instanceof Error ? error.message : String(error)}`, tone: "negative" });
    });
  }, []);

  const rows = payload.rows || [];
  const latest = payload.latest || rows[0] || {};

  return (
    <main className="min-h-screen bg-[#f0f0f0] p-3 text-rivr-ink md:p-5">
      <div className="mx-auto flex w-full max-w-[1536px] flex-col gap-5">
        <SummaryHero payload={{ ...payload, latest }} />
        <ActionPanel payload={{ ...payload, latest }} onRefresh={refreshData} onSendDiscord={sendDiscord} busy={busy} notice={notice} />
        <DashboardSections rows={rows} latest={latest} />
        <HistoryTable rows={rows} />
      </div>
    </main>
  );
}

export default App;
