"use client";

import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { Banner, Empty } from "@/components/ui";
import { del, get, patch, post } from "@/lib/api";
import { Deal, DealStage, PipelineSummary } from "@/lib/types";

const STAGES: { id: DealStage; label: string; colorStyle: string }[] = [
  { id: "PROSPECT", label: "Prospect", colorStyle: "border-zinc-700 bg-zinc-900/50" },
  { id: "CONTACTED", label: "Contacted", colorStyle: "border-sky-800 bg-sky-950/20" },
  { id: "QUALIFIED", label: "Qualified", colorStyle: "border-indigo-800 bg-indigo-950/20" },
  { id: "PROPOSAL_SENT", label: "Proposal Sent", colorStyle: "border-amber-800 bg-amber-950/20" },
  { id: "NEGOTIATION", label: "Negotiation", colorStyle: "border-purple-800 bg-purple-950/20" },
  { id: "WON", label: "Closed Won", colorStyle: "border-emerald-800 bg-emerald-950/20" },
  { id: "LOST", label: "Lost", colorStyle: "border-rose-900 bg-rose-950/20" },
];

export default function CRMPage() {
  const [pipeline, setPipeline] = useState<PipelineSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeDeal, setActiveDeal] = useState<Deal | null>(null);
  const [showNewModal, setShowNewModal] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newCompany, setNewCompany] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [newValue, setNewValue] = useState("2500");
  const [saving, setSaving] = useState(false);

  const loadPipeline = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await get<PipelineSummary>("/api/crm/pipeline");
      setPipeline(data);
    } catch (err: any) {
      setError(err?.message || "Failed to load CRM pipeline");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPipeline();
  }, []);

  const handleStageChange = async (dealId: number, newStage: DealStage) => {
    try {
      await patch(`/api/crm/deals/${dealId}`, { stage: newStage });
      loadPipeline();
      if (activeDeal && activeDeal.id === dealId) {
        setActiveDeal({ ...activeDeal, stage: newStage });
      }
    } catch (err: any) {
      setError(err?.message || "Failed to move deal");
    }
  };

  const handleCreateDeal = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle || !newCompany) return;
    try {
      setSaving(true);
      await post("/api/crm/deals", {
        title: newTitle,
        company_name: newCompany,
        contact_email: newEmail || null,
        value: parseFloat(newValue) || 0,
        stage: "PROSPECT",
      });
      setShowNewModal(false);
      setNewTitle("");
      setNewCompany("");
      setNewEmail("");
      loadPipeline();
    } catch (err: any) {
      setError(err?.message || "Failed to create deal");
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteDeal = async (id: number) => {
    if (!confirm("Are you sure you want to remove this deal?")) return;
    try {
      await del(`/api/crm/deals/${id}`);
      setActiveDeal(null);
      loadPipeline();
    } catch (err: any) {
      setError(err?.message || "Failed to delete deal");
    }
  };

  return (
    <Shell>
      <div className="space-y-6">
        {/* Header with KPI Metrics */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-zinc-100">CRM Deal Pipeline & Master Operations</h1>
            <p className="text-sm text-zinc-400">
              Track sales opportunities, synchronize multi-tab master Excel spreadsheets, and forecast revenue.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              className="btn btn-secondary text-xs"
              onClick={async () => {
                try {
                  const res = await post<{ status: string }>("/api/crm/sync-excel");
                  alert("Master Excel (.xlsx) and CSV successfully synchronized to disk!");
                  loadPipeline();
                } catch (e: any) {
                  alert(e?.message || "Sync failed");
                }
              }}
            >
              🔄 Sync Master Excel
            </button>
            <a
              href={`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/crm/export-excel`}
              download="MASTER_CRM_OPERATIONS.xlsx"
              className="btn btn-secondary text-xs"
              target="_blank"
              rel="noreferrer"
            >
              📊 Export Excel (.xlsx)
            </a>
            <a
              href={`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/crm/export-csv`}
              download="MASTER_CRM_OPERATIONS.csv"
              className="btn btn-secondary text-xs"
              target="_blank"
              rel="noreferrer"
            >
              📄 Export CSV
            </a>
            <button className="btn btn-primary text-xs" onClick={() => setShowNewModal(true)}>
              + New Opportunity
            </button>
          </div>
        </div>

        {error && <Banner kind="error">{error}</Banner>}

        {/* Revenue Forecasting Summary */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="card">
            <div className="tile-label">Total Pipeline Value</div>
            <div className="tile-value text-emerald-400">
              ${pipeline ? pipeline.total_pipeline_value.toLocaleString() : "0"}
            </div>
          </div>
          <div className="card">
            <div className="tile-label">Weighted Revenue Forecast</div>
            <div className="tile-value text-sky-400">
              ${pipeline ? Math.round(pipeline.forecasted_value).toLocaleString() : "0"}
            </div>
          </div>
          <div className="card">
            <div className="tile-label">Active Opportunities</div>
            <div className="tile-value">
              {pipeline ? pipeline.total_deals : 0} deals
            </div>
          </div>
        </div>

        {loading && !pipeline ? (
          <div className="flex justify-center py-20">
            <span className="spinner" />
          </div>
        ) : (
          /* Kanban Board */
          <div className="grid grid-cols-1 md:grid-cols-7 gap-3 overflow-x-auto pb-4">
            {STAGES.map((col) => {
              const stageData = pipeline?.stages.find((s) => s.stage === col.id);
              const deals = stageData?.deals || [];
              const totalVal = stageData?.total_value || 0;

              return (
                <div
                  key={col.id}
                  className={`flex flex-col rounded-xl border p-3 min-w-[220px] ${col.colorStyle}`}
                >
                  <div className="flex items-center justify-between border-b border-zinc-800 pb-2 mb-3">
                    <span className="text-xs font-bold uppercase tracking-wider text-zinc-200">
                      {col.label}
                    </span>
                    <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400">
                      {deals.length}
                    </span>
                  </div>
                  <div className="text-xs font-semibold text-emerald-400 mb-2">
                    ${totalVal.toLocaleString()}
                  </div>

                  <div className="space-y-2 flex-1 overflow-y-auto max-h-[600px]">
                    {deals.length === 0 ? (
                      <div className="text-center py-8 text-xs text-zinc-600">No deals</div>
                    ) : (
                      deals.map((deal) => (
                        <div
                          key={deal.id}
                          onClick={() => setActiveDeal(deal)}
                          className="cursor-pointer rounded-lg border border-zinc-800 bg-zinc-900/90 p-3 hover:border-zinc-600 hover:shadow-lg transition-all"
                        >
                          <div className="text-sm font-semibold text-zinc-100 truncate">
                            {deal.title}
                          </div>
                          <div className="text-xs text-zinc-400 truncate mt-0.5">
                            {deal.company_name}
                          </div>
                          <div className="mt-2 flex items-center justify-between text-xs">
                            <span className="font-bold text-emerald-400">
                              ${deal.value.toLocaleString()}
                            </span>
                            <span className="text-zinc-500">{deal.probability}% win</span>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Deal Detail / Stage Transition Modal */}
        {activeDeal && (
          <div className="modal-backdrop">
            <div className="modal-card max-w-lg">
              <div className="flex justify-between items-center mb-4">
                <h2 className="text-lg font-bold text-zinc-100">{activeDeal.title}</h2>
                <button className="btn btn-secondary" onClick={() => setActiveDeal(null)}>
                  ✕
                </button>
              </div>

              <div className="space-y-4 text-sm">
                <div className="grid grid-cols-2 gap-3 bg-zinc-900/80 p-3 rounded-lg border border-zinc-800">
                  <div>
                    <div className="text-xs text-zinc-500">Company</div>
                    <div className="font-semibold text-zinc-200">{activeDeal.company_name}</div>
                  </div>
                  <div>
                    <div className="text-xs text-zinc-500">Value</div>
                    <div className="font-semibold text-emerald-400">
                      ${activeDeal.value.toLocaleString()}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-zinc-500">Contact Email</div>
                    <div className="text-zinc-300">{activeDeal.contact_email || "None"}</div>
                  </div>
                  <div>
                    <div className="text-xs text-zinc-500">Win Probability</div>
                    <div className="text-sky-400">{activeDeal.probability}%</div>
                  </div>
                </div>

                {activeDeal.notes && (
                  <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3 text-xs text-zinc-400">
                    <div className="font-semibold text-zinc-300 mb-1">Notes & AI Context</div>
                    {activeDeal.notes}
                  </div>
                )}

                <div>
                  <label className="block text-xs font-medium text-zinc-400 mb-1">
                    Move Stage
                  </label>
                  <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
                    {STAGES.map((s) => (
                      <button
                        key={s.id}
                        type="button"
                        onClick={() => handleStageChange(activeDeal.id, s.id)}
                        className={`rounded px-2.5 py-1.5 text-xs font-medium transition-colors ${
                          activeDeal.stage === s.id
                            ? "bg-emerald-600 text-white"
                            : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
                        }`}
                      >
                        {s.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="flex justify-between items-center pt-4 border-t border-zinc-800">
                  <button className="btn btn-danger" onClick={() => handleDeleteDeal(activeDeal.id)}>
                    Delete Deal
                  </button>
                  <button className="btn btn-secondary" onClick={() => setActiveDeal(null)}>
                    Close
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Create Deal Modal */}
        {showNewModal && (
          <div className="modal-backdrop">
            <div className="modal-card max-w-lg">
              <div className="flex justify-between items-center mb-4">
                <h2 className="text-lg font-bold text-zinc-100">Create New Sales Opportunity</h2>
                <button className="btn btn-secondary" onClick={() => setShowNewModal(false)}>
                  ✕
                </button>
              </div>

              <form onSubmit={handleCreateDeal} className="space-y-4 text-sm">
                <div>
                  <label className="block text-xs font-medium text-zinc-300 mb-1">
                    Deal Title *
                  </label>
                  <input
                    type="text"
                    required
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                    placeholder="e.g. Modern Web Redesign"
                    className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-zinc-100 focus:border-emerald-500 focus:outline-none"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-zinc-300 mb-1">
                    Company Name *
                  </label>
                  <input
                    type="text"
                    required
                    value={newCompany}
                    onChange={(e) => setNewCompany(e.target.value)}
                    placeholder="e.g. Apex Dental Clinic"
                    className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-zinc-100 focus:border-emerald-500 focus:outline-none"
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-zinc-300 mb-1">
                      Contact Email
                    </label>
                    <input
                      type="email"
                      value={newEmail}
                      onChange={(e) => setNewEmail(e.target.value)}
                      placeholder="contact@company.com"
                      className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-zinc-100 focus:border-emerald-500 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-zinc-300 mb-1">
                      Estimated Value ($)
                    </label>
                    <input
                      type="number"
                      value={newValue}
                      onChange={(e) => setNewValue(e.target.value)}
                      className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-zinc-100 focus:border-emerald-500 focus:outline-none"
                    />
                  </div>
                </div>

                <div className="flex justify-end gap-2 pt-3">
                  <button className="btn btn-secondary" type="button" onClick={() => setShowNewModal(false)}>
                    Cancel
                  </button>
                  <button className="btn btn-primary" type="submit" disabled={saving}>
                    {saving ? "Creating..." : "Create Deal"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </Shell>
  );
}
