"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { Banner, Empty, Loading, StatusBadge, formatDate } from "@/components/ui";
import { get, post } from "@/lib/api";
import type { LeadImportResult, LeadStatus, PaginatedLeads } from "@/lib/types";

const STATUSES: (LeadStatus | "")[] = [
  "", "NEEDS_APPROVAL", "READY", "CONTACTED", "FOLLOWED_UP", "REPLIED",
  "POSITIVE", "NEGATIVE", "NEUTRAL", "UNSUBSCRIBED", "BOUNCED",
  "DO_NOT_CONTACT", "FAILED", "WON",
];
const PAGE_SIZE = 50;

export default function LeadsPage() {
  const [data, setData] = useState<PaginatedLeads | null>(null);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [country, setCountry] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Import Modal State
  const [showImport, setShowImport] = useState(false);
  const [importCsv, setImportCsv] = useState("");
  const [importCategory, setImportCategory] = useState("");
  const [importCountry, setImportCountry] = useState("");
  const [autoQualify, setAutoQualify] = useState(true);
  const [autoApprove, setAutoApprove] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<LeadImportResult | null>(null);


  const load = useCallback(async () => {
    const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
    if (status) params.set("status", status);
    if (search.trim()) params.set("search", search.trim());
    if (country.trim()) params.set("country", country.trim().toUpperCase());
    try {
      setData(await get<PaginatedLeads>(`/api/leads?${params}`));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load leads");
    }
  }, [page, status, search, country]);

  useEffect(() => {
    load();
  }, [load]);

  const toggle = (id: number) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (!data) return;
    setSelected((current) =>
      current.size === data.items.length ? new Set() : new Set(data.items.map((l) => l.id)),
    );
  };

  async function bulk(action: string) {
    if (!selected.size) return;
    if (action === "suppress" &&
        !window.confirm(`Permanently stop contacting ${selected.size} lead(s)?`)) return;
    setBusy(true);
    try {
      const result = await post<{ affected: number }>("/api/leads/bulk", {
        lead_ids: Array.from(selected), action,
      });
      setNotice(`${action.replace("_", " ")}: ${result.affected} lead(s)`);
      setSelected(new Set());
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bulk action failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      const content = event.target?.result as string;
      if (content) setImportCsv(content);
    };
    reader.readAsText(file);
  }

  async function handleImportSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!importCsv.trim()) {
      setError("Please paste spreadsheet / CSV data or select a file to import.");
      return;
    }
    setImporting(true);
    setImportResult(null);
    try {
      const res = await post<LeadImportResult>("/api/leads/import", {
        csv_data: importCsv,
        auto_qualify: autoQualify,
        auto_approve: autoApprove,
        default_category: importCategory.trim() || undefined,
        default_country: importCountry.trim().toUpperCase() || undefined,
      });
      setImportResult(res);
      setNotice(`Import completed: ${res.leads_created} qualified leads created (${res.leads_approved} approved).`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
    } finally {
      setImporting(false);
    }
  }

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <Shell>
      <div className="page-head">
        <div>
          <h1>Leads</h1>
          <p className="subtitle">
            {data ? `${data.total} lead${data.total === 1 ? "" : "s"}` : "Loading…"}
          </p>
        </div>
        <div>
          <button className="btn-primary" onClick={() => { setShowImport(true); setImportResult(null); }}>
            + Import Reference Sheet / CSV
          </button>
        </div>
      </div>

      {showImport && (
        <div className="card mb" style={{ border: "1px solid #3b82f6", background: "#f8fafc" }}>
          <div className="row mb" style={{ justifyContent: "space-between", alignItems: "center" }}>
            <h3 style={{ margin: 0 }}>Import Reference Sheet / Custom Leads</h3>
            <button className="btn-sm" onClick={() => setShowImport(false)}>✕ Close</button>
          </div>
          <p className="small dim mb">
            Upload or paste CSV, TSV, or JSON data. Columns like <code>name</code>, <code>email</code>, <code>website</code>, <code>phone</code>, <code>city</code>, <code>country</code>, <code>category</code> are automatically detected.
          </p>
          <form onSubmit={handleImportSubmit}>
            <div className="mb">
              <label className="small faint block mb-1">Select File (.csv, .tsv, .txt, .json):</label>
              <input type="file" accept=".csv,.tsv,.txt,.json" onChange={handleFileUpload} style={{ padding: "6px" }} />
            </div>
            <div className="mb">
              <label className="small faint block mb-1">Or Paste Tabular Data / CSV:</label>
              <textarea
                rows={5}
                className="mono"
                style={{ width: "100%", fontSize: "12px", fontFamily: "monospace" }}
                placeholder="name,email,website,phone,city,country,category&#10;Rossi Trattoria,info@rossis.ie,,+353 21 555 0100,Cork,IE,restaurant"
                value={importCsv}
                onChange={(e) => setImportCsv(e.target.value)}
              />
            </div>
            <div className="row mb" style={{ gap: "16px", flexWrap: "wrap" }}>
              <div>
                <label className="small faint block">Default Category (optional):</label>
                <input
                  placeholder="e.g. restaurant, plumber"
                  value={importCategory}
                  onChange={(e) => setImportCategory(e.target.value)}
                  style={{ width: 180 }}
                />
              </div>
              <div>
                <label className="small faint block">Default Country (optional):</label>
                <input
                  placeholder="e.g. IE, US, GB"
                  value={importCountry}
                  maxLength={2}
                  onChange={(e) => setImportCountry(e.target.value)}
                  style={{ width: 100 }}
                />
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "18px" }}>
                <input
                  type="checkbox"
                  id="autoQualify"
                  checked={autoQualify}
                  onChange={(e) => setAutoQualify(e.target.checked)}
                />
                <label htmlFor="autoQualify" className="small">Auto-qualify websites & emails</label>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "18px" }}>
                <input
                  type="checkbox"
                  id="autoApprove"
                  checked={autoApprove}
                  onChange={(e) => setAutoApprove(e.target.checked)}
                />
                <label htmlFor="autoApprove" className="small">Auto-approve for dispatch</label>
              </div>
            </div>
            <div className="row">
              <button type="submit" className="btn-primary" disabled={importing || !importCsv.trim()}>
                {importing ? "Processing Import…" : "Run Ingestion & Qualification"}
              </button>
            </div>
          </form>

          {importResult && (
            <div className="mt card" style={{ background: "#ffffff" }}>
              <h4>Import Summary</h4>
              <div className="row" style={{ gap: "20px", marginTop: "8px" }}>
                <div><span className="small faint">Rows parsed:</span> <strong>{importResult.total_rows}</strong></div>
                <div><span className="small faint">Businesses new:</span> <strong>{importResult.businesses_created}</strong></div>
                <div><span className="small faint">Businesses updated:</span> <strong>{importResult.businesses_updated}</strong></div>
                <div><span className="small faint">Leads created:</span> <strong>{importResult.leads_created}</strong></div>
                <div><span className="small faint">Leads approved:</span> <strong>{importResult.leads_approved}</strong></div>
              </div>
              {importResult.errors && importResult.errors.length > 0 && (
                <div className="mt">
                  <span className="small danger">Warnings / Issues:</span>
                  <ul className="small danger" style={{ margin: "4px 0 0 16px" }}>
                    {importResult.errors.map((err, i) => <li key={i}>{err}</li>)}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}


      {error && <Banner kind="error">{error}</Banner>}
      {notice && <Banner kind="ok">{notice}</Banner>}

      <div className="card mb">
        <div className="row">
          <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}
                  style={{ width: 190 }}>
            {STATUSES.map((option) => (
              <option key={option} value={option}>
                {option ? option.replace(/_/g, " ") : "All statuses"}
              </option>
            ))}
          </select>
          <input placeholder="Search name, email or city" value={search}
                 style={{ width: 260 }}
                 onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
          <input placeholder="Country (IE)" value={country} maxLength={2}
                 style={{ width: 130 }}
                 onChange={(e) => { setCountry(e.target.value); setPage(1); }} />
          <div style={{ flex: 1 }} />
          {selected.size > 0 && (
            <>
              <span className="small dim">{selected.size} selected</span>
              <button className="btn-sm btn-primary" disabled={busy}
                      onClick={() => bulk("approve")}>Approve</button>
              <button className="btn-sm" disabled={busy}
                      onClick={() => bulk("unapprove")}>Unapprove</button>
              <button className="btn-sm" disabled={busy}
                      onClick={() => bulk("send_now")}>Queue send</button>
              <button className="btn-sm btn-danger" disabled={busy}
                      onClick={() => bulk("suppress")}>Never contact</button>
            </>
          )}
        </div>
      </div>

      <div className="card" style={{ padding: 0 }}>
        {!data ? (
          <Loading />
        ) : data.items.length === 0 ? (
          <Empty>
            No leads match these filters. Run a discovery to find businesses without a website.
          </Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 34 }}>
                    <input type="checkbox" style={{ width: 15 }}
                           checked={selected.size === data.items.length}
                           onChange={toggleAll} aria-label="Select all" />
                  </th>
                  <th>Business</th>
                  <th>Email</th>
                  <th>Location</th>
                  <th>Web presence</th>
                  <th className="right">Score</th>
                  <th>Status</th>
                  <th>Last contact</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((lead) => (
                  <tr key={lead.id}>
                    <td>
                      <input type="checkbox" style={{ width: 15 }}
                             checked={selected.has(lead.id)} onChange={() => toggle(lead.id)}
                             aria-label={`Select ${lead.business.name}`} />
                    </td>
                    <td>
                      <Link href={`/leads/${lead.id}`}>{lead.business.name}</Link>
                      <div className="small faint">
                        {lead.business.category?.replace(/_/g, " ") ?? "—"}
                      </div>
                    </td>
                    <td className="mono truncate" title={lead.email}>
                      {lead.email}
                      {lead.is_role_account && <span className="faint small"> (role)</span>}
                    </td>
                    <td className="small">
                      {[lead.business.city, lead.business.country_code]
                        .filter(Boolean).join(", ") || "—"}
                    </td>
                    <td>
                      {!lead.business.website ? (
                        <span className="badge badge-blue">NO SITE</span>
                      ) : lead.business.website_alive === false ? (
                        <span className="badge badge-amber">BROKEN</span>
                      ) : (
                        <span className="badge badge-violet">SOCIAL ONLY</span>
                      )}
                    </td>
                    <td className="right mono">{lead.score.toFixed(0)}</td>
                    <td><StatusBadge status={lead.status} /></td>
                    <td className="small dim nowrap">{formatDate(lead.last_contacted_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {data && pages > 1 && (
        <div className="row mt" style={{ justifyContent: "center" }}>
          <button className="btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            Previous
          </button>
          <span className="small dim">Page {page} of {pages}</span>
          <button className="btn-sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>
            Next
          </button>
        </div>
      )}
    </Shell>
  );
}
