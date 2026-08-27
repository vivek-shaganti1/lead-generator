"use client";

import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { Banner, Empty, Loading, formatDate } from "@/components/ui";
import { get, post } from "@/lib/api";
import type { CategoryOption, DiscoveryRun } from "@/lib/types";

/** Handy starting boxes so you don't have to hunt for coordinates. */
const PRESETS = [
  { label: "Hyderabad, IN", country: "IN", bbox: { south: 17.24, west: 78.24, north: 17.60, east: 78.66 } },
  { label: "Bengaluru, IN", country: "IN", bbox: { south: 12.83, west: 77.45, north: 13.14, east: 77.78 } },
  { label: "Mumbai, IN", country: "IN", bbox: { south: 18.89, west: 72.77, north: 19.27, east: 72.98 } },
  { label: "Dublin, IE", country: "IE", bbox: { south: 53.28, west: -6.39, north: 53.41, east: -6.11 } },
  { label: "London, GB", country: "GB", bbox: { south: 51.36, west: -0.35, north: 51.62, east: 0.09 } },
  { label: "Austin, US", country: "US", bbox: { south: 30.14, west: -97.94, north: 30.52, east: -97.57 } },
  { label: "Sydney, AU", country: "AU", bbox: { south: -33.95, west: 150.99, north: -33.75, east: 151.29 } },
  { label: "Dubai, AE", country: "AE", bbox: { south: 25.03, west: 55.09, north: 25.34, east: 55.42 } },
];

export default function DiscoveryPage() {
  const [categories, setCategories] = useState<CategoryOption[]>([]);
  const [runs, setRuns] = useState<DiscoveryRun[]>([]);
  const [chosen, setChosen] = useState<string[]>(["restaurant", "cafe", "salon"]);
  const [label, setLabel] = useState("Hyderabad, IN");
  const [country, setCountry] = useState("IN");
  const [bbox, setBbox] = useState(PRESETS[0].bbox);
  const [limit, setLimit] = useState(500);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadRuns = useCallback(async () => {
    try {
      setRuns(await get<DiscoveryRun[]>("/api/discovery/runs?limit=30"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load runs");
    }
  }, []);

  useEffect(() => {
    get<CategoryOption[]>("/api/discovery/categories").then(setCategories).catch(() => undefined);
    loadRuns();
    const timer = setInterval(loadRuns, 15_000);
    return () => clearInterval(timer);
  }, [loadRuns]);

  function applyPreset(name: string) {
    const preset = PRESETS.find((p) => p.label === name);
    if (!preset) return;
    setLabel(preset.label);
    setCountry(preset.country);
    setBbox(preset.bbox);
  }

  async function run() {
    if (!chosen.length) {
      setError("Pick at least one category");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await post("/api/discovery/run", {
        label, bbox, country_code: country.toUpperCase() || null,
        categories: chosen, limit, run_async: true,
      });
      setNotice(`Discovery queued for ${label}. Results appear below as the worker finishes.`);
      await loadRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start discovery");
    } finally {
      setBusy(false);
    }
  }

  const toggleCategory = (key: string) =>
    setChosen((current) =>
      current.includes(key) ? current.filter((c) => c !== key) : [...current, key],
    );

  return (
    <Shell>
      <div className="page-head">
        <div>
          <h1>Discovery</h1>
          <p className="subtitle">
            Search an area on OpenStreetMap for businesses with no working website.
          </p>
        </div>
      </div>

      {error && <Banner kind="error">{error}</Banner>}
      {notice && <Banner kind="ok">{notice}</Banner>}

      <div className="card mb">
        <h2>New search</h2>
        <div className="grid grid-3 mb">
          <div className="field">
            <label htmlFor="preset">Start from a city</label>
            <select id="preset" onChange={(e) => applyPreset(e.target.value)}
                    defaultValue={PRESETS[0].label}>
              {PRESETS.map((preset) => (
                <option key={preset.label} value={preset.label}>{preset.label}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="label">Label for this run</label>
            <input id="label" value={label} onChange={(e) => setLabel(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="country">Country code</label>
            <input id="country" maxLength={2} value={country}
                   onChange={(e) => setCountry(e.target.value.toUpperCase())} />
          </div>
        </div>

        <div className="grid grid-4 mb">
          {(["south", "west", "north", "east"] as const).map((corner) => (
            <div className="field" key={corner}>
              <label htmlFor={corner}>{corner}</label>
              <input id={corner} type="number" step="0.0001" value={bbox[corner]}
                     onChange={(e) =>
                       setBbox({ ...bbox, [corner]: Number(e.target.value) })} />
            </div>
          ))}
        </div>

        <h3>Categories ({chosen.length} selected)</h3>
        <div className="row mb" style={{ gap: 6 }}>
          {categories.map((category) => (
            <button key={category.key}
                    className={`btn-sm ${chosen.includes(category.key) ? "btn-primary" : ""}`}
                    onClick={() => toggleCategory(category.key)}>
              {category.label}
            </button>
          ))}
        </div>

        <div className="row">
          <div style={{ width: 160 }}>
            <label htmlFor="limit">Max results</label>
            <input id="limit" type="number" min={1} max={5000} value={limit}
                   onChange={(e) => setLimit(Number(e.target.value))} />
          </div>
          <div style={{ flex: 1 }} />
          <button className="btn-primary" onClick={run} disabled={busy}>
            {busy ? "Starting…" : "Run discovery"}
          </button>
        </div>
        <p className="small faint mt">
          Large boxes take a while: Overpass is a shared free service and we deliberately
          keep a gap between requests. Discovered businesses are enriched and turned into
          leads by the background worker within a few minutes.
        </p>
      </div>

      <div className="card" style={{ padding: 0 }}>
        {!runs ? (
          <Loading />
        ) : runs.length === 0 ? (
          <Empty>No discovery runs yet.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Area</th>
                  <th>Provider</th>
                  <th>Status</th>
                  <th className="right">Found</th>
                  <th className="right">No website</th>
                  <th className="right">New</th>
                  <th>Started</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((row) => (
                  <tr key={row.id}>
                    <td>{row.area_label}</td>
                    <td className="small dim">{row.provider}</td>
                    <td>
                      <span className={`badge badge-${
                        row.status === "SUCCESS" ? "green"
                          : row.status === "FAILED" ? "red"
                            : row.status === "PARTIAL" ? "amber" : "blue"}`}>
                        {row.status}
                      </span>
                    </td>
                    <td className="right mono">{row.found_total}</td>
                    <td className="right mono">{row.without_website}</td>
                    <td className="right mono">{row.new_businesses}</td>
                    <td className="small dim nowrap">{formatDate(row.started_at)}</td>
                    <td className="small truncate" title={row.error ?? ""}>{row.error ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Shell>
  );
}
