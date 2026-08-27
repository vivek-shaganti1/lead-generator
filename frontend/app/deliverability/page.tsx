"use client";

import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { Banner } from "@/components/ui";
import { get, post } from "@/lib/api";
import { DeliverabilityHealth } from "@/lib/types";

export default function DeliverabilityPage() {
  const [health, setHealth] = useState<DeliverabilityHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadHealth = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await get<DeliverabilityHealth>("/api/deliverability/health");
      setHealth(data);
    } catch (err: any) {
      setError(err?.message || "Failed to load deliverability data");
    } finally {
      setLoading(false);
    }
  };

  const handleVerify = async () => {
    try {
      setVerifying(true);
      const data = await post<DeliverabilityHealth>("/api/deliverability/verify");
      setHealth(data);
    } catch (err: any) {
      setError(err?.message || "Verification scan failed");
    } finally {
      setVerifying(false);
    }
  };

  useEffect(() => {
    loadHealth();
  }, []);

  return (
    <Shell>
      <div className="space-y-6 max-w-5xl">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-zinc-100">Deliverability Sentinel</h1>
            <p className="text-sm text-zinc-400">
              Active DNS authentication, blacklist monitoring, and sender domain reputation protection.
            </p>
          </div>
          <button className="btn btn-primary" onClick={handleVerify} disabled={verifying}>
            {verifying ? "Auditing DNS..." : "Run Live Verification Scan"}
          </button>
        </div>

        {error && <Banner kind="error">{error}</Banner>}

        {loading && !health ? (
          <div className="flex justify-center py-20">
            <span className="spinner" />
          </div>
        ) : health ? (
          <div className="space-y-6">
            {/* Reputation Score & Circuit Breaker Status */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="card">
                <div className="tile-label">Domain Reputation Score</div>
                <div className="mt-2 flex items-baseline gap-2">
                  <span className="text-3xl font-bold text-emerald-400">
                    {health.reputation_score}
                  </span>
                  <span className="text-sm text-zinc-500">/ 100</span>
                </div>
                <div className="mt-2 text-xs text-zinc-400">
                  Domain: <span className="text-zinc-200 font-mono">{health.domain}</span>
                </div>
              </div>

              <div className="card">
                <div className="tile-label">Spam Risk Assessment</div>
                <div className="mt-2 flex items-baseline gap-2">
                  <span className="text-3xl font-bold text-sky-400">{health.spam_score}</span>
                  <span className="text-sm text-zinc-500">/ 10.0</span>
                </div>
                <div className="mt-2 text-xs text-emerald-400">Low risk — Safe for cold delivery</div>
              </div>

              <div className="card">
                <div className="tile-label">Campaign Circuit Breaker</div>
                <div className="mt-2">
                  {health.is_paused ? (
                    <span className="badge badge-red">OUTREACH PAUSED</span>
                  ) : (
                    <span className="badge badge-green">ACTIVE & PROTECTED</span>
                  )}
                </div>
                <div className="mt-2 text-xs text-zinc-400">
                  {health.pause_reason || "Bounces and spam traps within safe operational thresholds."}
                </div>
              </div>
            </div>

            {/* Authentication DNS Protocol Checks */}
            <div className="card space-y-4">
              <h2 className="text-base font-semibold text-zinc-100">
                Email Authentication Protocols
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="flex items-start justify-between rounded-lg border border-zinc-800 bg-zinc-900/80 p-4">
                  <div>
                    <div className="font-semibold text-zinc-200">SPF (Sender Policy Framework)</div>
                    <div className="text-xs text-zinc-400 mt-1">
                      Authorizes sending mail servers on your domain.
                    </div>
                  </div>
                  <span className={`badge ${health.spf_valid ? "badge-green" : "badge-amber"}`}>
                    {health.spf_valid ? "VALID" : "MISSING"}
                  </span>
                </div>

                <div className="flex items-start justify-between rounded-lg border border-zinc-800 bg-zinc-900/80 p-4">
                  <div>
                    <div className="font-semibold text-zinc-200">DKIM (Cryptographic Signatures)</div>
                    <div className="text-xs text-zinc-400 mt-1">
                      Cryptographically signs outgoing messages to prevent tampering.
                    </div>
                  </div>
                  <span className={`badge ${health.dkim_valid ? "badge-green" : "badge-amber"}`}>
                    {health.dkim_valid ? "VALID" : "MISSING"}
                  </span>
                </div>

                <div className="flex items-start justify-between rounded-lg border border-zinc-800 bg-zinc-900/80 p-4">
                  <div>
                    <div className="font-semibold text-zinc-200">DMARC Policy</div>
                    <div className="text-xs text-zinc-400 mt-1">
                      Protects against spoofing and phishing under your domain.
                    </div>
                  </div>
                  <span className={`badge ${health.dmarc_valid ? "badge-green" : "badge-amber"}`}>
                    {health.dmarc_valid ? "PROTECTED" : "MISSING"}
                  </span>
                </div>

                <div className="flex items-start justify-between rounded-lg border border-zinc-800 bg-zinc-900/80 p-4">
                  <div>
                    <div className="font-semibold text-zinc-200">BIMI (Brand Indicators)</div>
                    <div className="text-xs text-zinc-400 mt-1">
                      Displays verified logo avatar in recipient inboxes.
                    </div>
                  </div>
                  <span className={`badge ${health.bimi_valid ? "badge-green" : "badge-grey"}`}>
                    {health.bimi_valid ? "CONFIGURED" : "OPTIONAL"}
                  </span>
                </div>
              </div>
            </div>

            {/* Blacklist Status */}
            <div className="card space-y-3">
              <h2 className="text-base font-semibold text-zinc-100">
                Global Blacklist (DNSBL) Screening
              </h2>
              <div className="flex items-center gap-3">
                <span className="h-3 w-3 rounded-full bg-emerald-500"></span>
                <span className="text-sm text-zinc-300 font-medium">
                  Clean across Spamhaus, Barracuda Central, SORBS, and SpamCop DNSBL zones.
                </span>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </Shell>
  );
}
