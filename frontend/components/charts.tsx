"use client";

import { formatDay } from "./ui";

export interface Series<T = Record<string, unknown>> {
  /** Must name a field that exists on the row type, so a typo is a compile error. */
  key: keyof T & string;
  label: string;
  color: string;
}

/**
 * Small multi-series line chart drawn as raw SVG.
 * No charting dependency: the shapes here are simple enough that a library
 * would cost more than it saves.
 */
export function LineChart<T extends { day: string }>({
  data, series, height = 190,
}: {
  data: T[];
  series: Series<T>[];
  height?: number;
}) {
  const width = 760;
  const pad = { top: 12, right: 12, bottom: 26, left: 34 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;

  const values = data.flatMap((row) => series.map((s) => Number(row[s.key] ?? 0)));
  const max = Math.max(1, ...values);
  const stepX = data.length > 1 ? innerW / (data.length - 1) : 0;

  const x = (i: number) => pad.left + i * stepX;
  const y = (v: number) => pad.top + innerH - (v / max) * innerH;

  const ticks = [0, 0.5, 1].map((t) => Math.round(max * t));
  const labelEvery = Math.max(1, Math.ceil(data.length / 7));

  return (
    <div>
      <svg className="chart" viewBox={`0 0 ${width} ${height}`} role="img"
           aria-label="Activity over time">
        {ticks.map((tick) => (
          <g key={tick}>
            <line x1={pad.left} x2={width - pad.right} y1={y(tick)} y2={y(tick)}
                  stroke="var(--border)" strokeWidth="1" />
            <text x={pad.left - 7} y={y(tick) + 4} textAnchor="end"
                  fontSize="10" fill="var(--text-faint)">{tick}</text>
          </g>
        ))}

        {series.map((s) => {
          const points = data.map((row, i) => `${x(i)},${y(Number(row[s.key] ?? 0))}`);
          return (
            <g key={s.key}>
              <polyline points={points.join(" ")} fill="none" stroke={s.color}
                        strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
              {data.length <= 40 &&
                data.map((row, i) => (
                  <circle key={i} cx={x(i)} cy={y(Number(row[s.key] ?? 0))} r="2.5"
                          fill={s.color}>
                    <title>{`${row.day}: ${String(row[s.key] ?? 0)} ${s.label}`}</title>
                  </circle>
                ))}
            </g>
          );
        })}

        {data.map((row, i) =>
          i % labelEvery === 0 ? (
            <text key={i} x={x(i)} y={height - 7} textAnchor="middle" fontSize="10"
                  fill="var(--text-faint)">
              {formatDay(String(row.day))}
            </text>
          ) : null,
        )}
      </svg>

      <div className="legend">
        {series.map((s) => (
          <span key={s.key} className="legend-item">
            <span className="legend-swatch" style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}

export function BarList({
  rows, color = "var(--accent)", emptyLabel = "No data yet",
}: {
  rows: { label: string; value: number }[];
  color?: string;
  emptyLabel?: string;
}) {
  if (!rows.length) return <div className="empty">{emptyLabel}</div>;
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div>
      {rows.map((row) => (
        <div className="bar-row" key={row.label}>
          <span className="truncate dim" title={row.label}>{row.label}</span>
          <span className="bar-track">
            <span className="bar-fill"
                  style={{ width: `${(row.value / max) * 100}%`, background: color }} />
          </span>
          <span className="right mono">{row.value}</span>
        </div>
      ))}
    </div>
  );
}

export function Funnel({ rows }: { rows: { stage: string; count: number; pct_of_top: number }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  const colors = ["#4f8cff", "#5b9dff", "#7c8cff", "#a78bfa", "#c084fc", "#34d399", "#10b981"];
  return (
    <div>
      {rows.map((row, i) => (
        <div className="bar-row" key={row.stage}>
          <span className="truncate dim" title={row.stage}>{row.stage}</span>
          <span className="bar-track">
            <span className="bar-fill"
                  style={{
                    width: `${Math.max((row.count / max) * 100, row.count ? 2 : 0)}%`,
                    background: colors[i % colors.length],
                  }} />
          </span>
          <span className="right mono" title={`${row.pct_of_top}% of discovered`}>
            {row.count}
          </span>
        </div>
      ))}
    </div>
  );
}
