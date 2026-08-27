"use client";

import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { Banner } from "@/components/ui";
import { get } from "@/lib/api";
import { LearningInsight } from "@/lib/types";

export default function LearningPage() {
  const [insights, setInsights] = useState<LearningInsight[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadInsights = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await get<LearningInsight[]>("/api/system/learning-insights");
      setInsights(data);
    } catch (err: any) {
      setError(err?.message || "Failed to load learning insights");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadInsights();
  }, []);

  return (
    <Shell>
      <div className="space-y-6 max-w-5xl">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-zinc-100">AI Learning & Conversion Engine</h1>
            <p className="text-sm text-zinc-400">
              Autonomous telemetry analyzing open rates, positive responses, and conversion patterns.
            </p>
          </div>
          <button className="btn btn-secondary" onClick={loadInsights}>
            Refresh Insights
          </button>
        </div>

        {error && <Banner kind="error">{error}</Banner>}

        {loading ? (
          <div className="flex justify-center py-20">
            <span className="spinner" />
          </div>
        ) : (
          <div className="space-y-4">
            {insights.map((item, idx) => (
              <div
                key={idx}
                className="card space-y-3"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold uppercase tracking-wider text-emerald-400">
                    {item.category}
                  </span>
                  <span className={`badge ${item.impact_level === "HIGH" ? "badge-green" : "badge-grey"}`}>
                    {item.impact_level} IMPACT
                  </span>
                </div>
                <h3 className="text-lg font-semibold text-zinc-100">{item.headline}</h3>
                <p className="text-sm text-zinc-400">{item.description}</p>
                <div className="rounded-lg bg-zinc-950/80 border border-zinc-800 p-3 text-xs text-zinc-300">
                  <span className="font-semibold text-emerald-400">AI Recommended Action: </span>
                  {item.recommended_action}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Shell>
  );
}
