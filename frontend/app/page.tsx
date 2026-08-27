"use client";

import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { BarList, Funnel, LineChart } from "@/components/charts";
import { Banner, Loading, Tile, formatDate, pct } from "@/components/ui";
import { get } from "@/lib/api";
import type { Dashboard } from "@/lib/types";

const RANGES = [7, 14, 30, 90];

export default function DashboardPage() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (range: number) => {
    try {
      setData(await get<Dashboard>(`/api/stats/dashboard?days=${range}`));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the dashboard");
    }
  }, []);

  useEffect(() => {
    load(days);
    const timer = setInterval(() => load(days), 60_000);
    return () => clearInterval(timer);
  }, [days, load]);

  return (
    <Shell>
      <div className="page-head">
        <div>
          <h1>Dashboard</h1>
          <p className="subtitle">
            {data ? `Updated ${formatDate(data.generated_at)}` : "Loading…"}
          </p>
        </div>
        <div className="row">
          {RANGES.map((range) => (
            <button key={range} className={`btn-sm ${range === days ? "btn-primary" : ""}`}
                    onClick={() => setDays(range)}>
              {range}d
            </button>
          ))}
        </div>
      </div>

      {error && <Banner kind="error">{error}</Banner>}
      {!data ? (
        <Loading />
      ) : (
        <div className="stack">
          {data.sending.dry_run && (
            <Banner kind="warn">
              <span>
                <strong>Dry run is on.</strong> Every message is rendered and recorded but
                nothing is delivered. Set <code>DRY_RUN=false</code> when you are ready to
                send for real.
              </span>
            </Banner>
          )}

          {/* Today's sending budget */}
          <div className="card">
            <div className="spread mb">
              <h2 style={{ margin: 0 }}>Today&apos;s sending</h2>
              <span className="small dim">
                {data.sending.warmup_enabled
                  ? `Warm-up day ${data.sending.warmup_day + 1}`
                  : "Warm-up off"}
              </span>
            </div>
            <div className="bar-row">
              <span className="dim">Sent / cap</span>
              <span className="bar-track">
                <span className="bar-fill"
                      style={{
                        width: `${Math.min(100, (data.sending.sent / Math.max(1, data.sending.cap)) * 100)}%`,
                        background: "var(--accent)",
                      }} />
              </span>
              <span className="right mono">
                {data.sending.sent}/{data.sending.cap}
              </span>
            </div>
            <div className="small dim">{data.sending.remaining} left in today&apos;s budget</div>
          </div>

          {/* The two sides: what went out, what came back */}
          <div className="grid grid-2">
            <div className="card">
              <div className="split-head">
                <span className="split-dot" style={{ background: "var(--accent)" }} />
                <h2 style={{ margin: 0 }}>Outbound</h2>
              </div>
              <div className="grid grid-4">
                <Tile label="Discovered" value={data.totals.outbound.businesses_discovered}
                      sub={`${data.totals.outbound.without_website} with no site`} />
                <Tile label="Leads" value={data.totals.outbound.leads}
                      sub="contactable" />
                <Tile label="Emails sent" value={data.totals.outbound.emails_sent}
                      sub={`${data.totals.outbound.unique_contacted} businesses`} />
                <Tile label="Open rate" value={pct(data.totals.outbound.open_rate)}
                      sub={`${data.totals.outbound.opened} opened`} />
              </div>
            </div>

            <div className="card">
              <div className="split-head">
                <span className="split-dot" style={{ background: "var(--green)" }} />
                <h2 style={{ margin: 0 }}>Inbound</h2>
              </div>
              <div className="grid grid-4">
                <Tile label="Replies" value={data.totals.inbound.replies}
                      sub={`${pct(data.totals.inbound.reply_rate)} reply rate`} />
                <Tile label="Positive" value={data.totals.inbound.positive} tone="green"
                      sub={`${pct(data.totals.inbound.positive_rate)} of replies`} />
                <Tile label="Negative" value={data.totals.inbound.negative} tone="red"
                      sub={`${data.totals.inbound.unsubscribes} opt-outs`} />
                <Tile label="Bounces" value={data.totals.inbound.bounces}
                      tone={data.totals.inbound.bounce_rate > 3 ? "red" : undefined}
                      sub={`${pct(data.totals.inbound.bounce_rate)} of sends`} />
              </div>
            </div>
          </div>

          {data.totals.inbound.bounce_rate > 3 && (
            <Banner kind="error">
              Bounce rate is {pct(data.totals.inbound.bounce_rate)}. Anything above ~3%
              puts your sending domain at risk — pause and review where the addresses
              are coming from.
            </Banner>
          )}

          <div className="grid grid-2">
            <div className="card">
              <h2>Sending activity</h2>
              <LineChart
                data={data.timeseries}
                series={[
                  { key: "emails_sent", label: "First emails", color: "#4f8cff" },
                  { key: "followups_sent", label: "Follow-ups", color: "#a78bfa" },
                  { key: "opened", label: "Opened", color: "#fbbf24" },
                ]}
              />
            </div>
            <div className="card">
              <h2>Responses</h2>
              <LineChart
                data={data.timeseries}
                series={[
                  { key: "positive", label: "Positive", color: "#34d399" },
                  { key: "negative", label: "Negative", color: "#f87171" },
                  { key: "replies", label: "All replies", color: "#4f8cff" },
                ]}
              />
            </div>
          </div>

          <div className="grid grid-3">
            <div className="card">
              <h2>Funnel</h2>
              <Funnel rows={data.funnel} />
            </div>
            <div className="card">
              <h2>Leads by status</h2>
              <BarList
                rows={data.by_status.map((row) => ({
                  label: row.status.replace(/_/g, " "), value: row.count,
                }))}
                color="var(--violet)"
                emptyLabel="No leads yet"
              />
            </div>
            <div className="card">
              <h2>Top countries</h2>
              <BarList
                rows={data.by_country.map((row) => ({ label: row.key, value: row.count }))}
                color="var(--green)"
                emptyLabel="Run a discovery to populate this"
              />
              <h2 className="mt">Top categories</h2>
              <BarList
                rows={data.by_category.slice(0, 8).map((row) => ({
                  label: row.key.replace(/_/g, " "), value: row.count,
                }))}
                color="var(--amber)"
                emptyLabel="—"
              />
            </div>
          </div>
        </div>
      )}
    </Shell>
  );
}
