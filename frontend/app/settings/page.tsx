"use client";

import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import {
  Banner, Empty, KeyValue, Loading, Meter, StatusDot, Toggle, formatDate,
} from "@/components/ui";
import { del, get, post } from "@/lib/api";
import type {
  AppConfig, EmailTestResult, GroqTestResult, SendingStatus, Suppression,
  SuppressionInput, SystemHealth, TelegramTestResult,
} from "@/lib/types";

type TestKey = "email" | "telegram" | "groq";
type TestState = { status: "idle" | "pending" | "ok" | "error"; message: string };

const IDLE: TestState = { status: "idle", message: "" };

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
const DOMAIN_RE = /^(?!-)[a-z0-9-]+(\.[a-z0-9-]+)+$/i;

const BLANK_SUPPRESSION: SuppressionInput = { value: "", kind: "email", reason: "manual" };

/** Mirrors the backend's SuppressionIn constraints so bad input never reaches the API. */
function validateSuppression(form: SuppressionInput): string | null {
  const value = form.value.trim();
  if (!value) return "Enter an email address or a domain";
  if (value.length < 3) return "Value must be at least 3 characters";
  if (value.length > 320) return "Value must be at most 320 characters";
  if (form.kind === "email" && !EMAIL_RE.test(value)) return "That is not a valid email address";
  if (form.kind === "domain") {
    if (value.includes("@")) return "Enter a bare domain, without the mailbox part";
    if (!DOMAIN_RE.test(value)) return "That is not a valid domain (e.g. example.com)";
  }
  if (form.reason.length > 255) return "Reason must be at most 255 characters";
  return null;
}

function hourLabel(hour: number): string {
  return `${String(hour).padStart(2, "0")}:00`;
}

export default function SettingsPage() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [sending, setSending] = useState<SendingStatus | null>(null);
  const [suppressions, setSuppressions] = useState<Suppression[] | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const [form, setForm] = useState<SuppressionInput>({ ...BLANK_SUPPRESSION });
  const [formError, setFormError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [removingId, setRemovingId] = useState<number | null>(null);

  const [testEmail, setTestEmail] = useState("");
  const [tests, setTests] = useState<Record<TestKey, TestState>>({
    email: IDLE, telegram: IDLE, groq: IDLE,
  });

  const setTest = (key: TestKey, state: TestState) =>
    setTests((current) => ({ ...current, [key]: state }));

  const loadHealth = useCallback(async () => {
    setHealth(await get<SystemHealth>("/api/system/health"));
  }, []);

  const loadSuppressions = useCallback(async () => {
    setSuppressions(await get<Suppression[]>("/api/system/suppressions"));
  }, []);

  const loadAll = useCallback(async () => {
    setRefreshing(true);
    try {
      const [healthOut, configOut, sendingOut, suppressionsOut] = await Promise.all([
        get<SystemHealth>("/api/system/health"),
        get<AppConfig>("/api/system/config"),
        get<SendingStatus>("/api/system/sending"),
        get<Suppression[]>("/api/system/suppressions"),
      ]);
      setHealth(healthOut);
      setConfig(configOut);
      setSending(sendingOut);
      setSuppressions(suppressionsOut);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load system settings");
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  async function refreshHealth() {
    setRefreshing(true);
    try {
      await loadHealth();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Health check failed");
    } finally {
      setRefreshing(false);
    }
  }

  async function addSuppression(event: React.FormEvent) {
    event.preventDefault();
    const problem = validateSuppression(form);
    setFormError(problem);
    if (problem) return;

    setAdding(true);
    setNotice(null);
    try {
      const created = await post<Suppression>("/api/system/suppressions", {
        value: form.value.trim(),
        kind: form.kind,
        reason: form.reason.trim() || "manual",
      });
      setNotice(`${created.value} will never be contacted again`);
      setForm({ ...BLANK_SUPPRESSION });
      await loadSuppressions();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not add suppression");
    } finally {
      setAdding(false);
    }
  }

  async function removeSuppression(entry: Suppression) {
    if (!window.confirm(`Remove ${entry.value} from the suppression list?`)) return;
    setRemovingId(entry.id);
    setNotice(null);
    try {
      await del(`/api/system/suppressions/${entry.id}`);
      setNotice(`${entry.value} removed — it can be contacted again`);
      await loadSuppressions();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not remove suppression");
    } finally {
      setRemovingId(null);
    }
  }

  async function runEmailTest() {
    const address = testEmail.trim();
    if (!EMAIL_RE.test(address)) {
      setTest("email", { status: "error", message: "Enter a valid destination address first" });
      return;
    }
    setTest("email", { status: "pending", message: "Sending…" });
    try {
      const result = await post<EmailTestResult>("/api/system/test/email", { to_email: address });
      setTest("email", {
        status: "ok",
        message: result.dry_run
          ? `Dry run — the message was rendered and logged, not delivered${
              result.message_id ? ` (${result.message_id})` : ""
            }`
          : `Delivered to ${address}${result.message_id ? ` (${result.message_id})` : ""}`,
      });
    } catch (err) {
      setTest("email", {
        status: "error",
        message: err instanceof Error ? err.message : "Send failed",
      });
    }
  }

  async function runTelegramTest() {
    setTest("telegram", { status: "pending", message: "Sending…" });
    try {
      const result = await post<TelegramTestResult>("/api/system/test/telegram");
      setTest("telegram", {
        status: result.sent ? "ok" : "error",
        message: result.sent
          ? "Message delivered — check your Telegram chat"
          : "Telegram did not accept the message",
      });
    } catch (err) {
      setTest("telegram", {
        status: "error",
        message: err instanceof Error ? err.message : "Telegram test failed",
      });
    }
  }

  async function runGroqTest() {
    setTest("groq", { status: "pending", message: "Classifying a sample reply…" });
    try {
      const result = await post<GroqTestResult>("/api/system/test/groq");
      setTest("groq", {
        status: "ok",
        message: `${result.classifier} → ${result.classification} (${Math.round(
          result.confidence * 100,
        )}% confidence)${result.summary ? ` — ${result.summary}` : ""}`,
      });
    } catch (err) {
      setTest("groq", {
        status: "error",
        message: err instanceof Error ? err.message : "Groq test failed",
      });
    }
  }

  const loading = !health && !config && !sending && !suppressions;

  return (
    <Shell>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p className="subtitle">
            Everything here is read from the environment the server booted with. To change
            a value, edit <code className="mono">.env</code> and restart — nothing on this
            page is editable, so a running system can never drift from its configuration.
          </p>
        </div>
        <button onClick={loadAll} disabled={refreshing}>
          {refreshing ? "Refreshing…" : "Refresh all"}
        </button>
      </div>

      {error && <Banner kind="error">{error}</Banner>}
      {notice && <Banner kind="ok">{notice}</Banner>}

      {loading ? (
        <Loading />
      ) : (
        <div className="stack">
          {/* ------------------------------------------------ dry run ---- */}
          {config && (
            <div className={`dry-run-callout ${config.dry_run ? "" : "live"}`}>
              <span className="dry-run-tag">{config.dry_run ? "DRY RUN" : "LIVE SENDING"}</span>
              <span className="small">
                {config.dry_run ? (
                  <>
                    No mail leaves this machine. Messages are fully rendered, recorded and
                    counted against your quota, but the SMTP delivery step is skipped. Set{" "}
                    <code className="mono">DRY_RUN=false</code> when you are ready to send
                    for real.
                  </>
                ) : (
                  <>
                    Mail is being delivered to real recipients. Every send counts against the
                    daily cap and is subject to the warm-up ramp and send window below.
                  </>
                )}
              </span>
            </div>
          )}

          {/* ------------------------------------------------- health ---- */}
          <div className="card">
            <div className="spread mb">
              <h2 style={{ margin: 0 }}>System health</h2>
              <div className="row">
                {health && (
                  <span className={`badge badge-${health.status === "ok" ? "green" : "amber"}`}>
                    {health.status}
                  </span>
                )}
                <button className="btn-sm" onClick={refreshHealth} disabled={refreshing}>
                  {refreshing ? "Checking…" : "Re-check"}
                </button>
              </div>
            </div>

            {!health ? (
              <Empty>Health check unavailable.</Empty>
            ) : (
              <>
                <div className="grid grid-2">
                  <div>
                    <h3>Core</h3>
                    <StatusDot ok={health.database} label="Database" badText="Unreachable" />
                    <StatusDot ok={health.redis} label="Redis" badText="Unreachable" />
                  </div>
                  <div>
                    <h3>Integrations</h3>
                    <StatusDot ok={health.smtp_configured} label="SMTP (outbound mail)"
                               okText="Configured" badText="Not set" />
                    <StatusDot ok={health.imap_configured} label="IMAP (replies & bounces)"
                               okText="Configured" badText="Not set" />
                    <StatusDot ok={health.telegram_configured} label="Telegram notifications"
                               okText="Configured" badText="Not set" neutral />
                    <StatusDot ok={health.groq_configured} label="Groq (AI reply classifier)"
                               okText="Configured" badText="Not set" neutral />
                  </div>
                </div>
                <div className="row mt small faint">
                  <span>Version {health.version}</span>
                  <span>·</span>
                  <span>Environment {health.env}</span>
                </div>
              </>
            )}
          </div>

          {/* ------------------------------------------------ sending ---- */}
          <div className="card">
            <div className="spread mb">
              <h2 style={{ margin: 0 }}>Today&apos;s sending</h2>
              {sending && (
                <span className="badge badge-grey">
                  {sending.warmup_enabled ? `Warm-up day ${sending.warmup_day + 1}` : "No warm-up"}
                </span>
              )}
            </div>

            {!sending ? (
              <Empty>No sending data.</Empty>
            ) : (
              <>
                <Meter
                  value={sending.sent}
                  max={sending.cap}
                  tone={sending.remaining === 0 ? "amber" : "accent"}
                />
                <div className="spread mt small">
                  <span className="dim">
                    <strong>{sending.sent}</strong> sent of {sending.cap} allowed today
                  </span>
                  <span className="faint">{sending.day}</span>
                </div>
                <div className="grid grid-3 mt">
                  <KeyValue label="Remaining" value={sending.remaining} />
                  <KeyValue label="Cap today" value={sending.cap} />
                  <KeyValue
                    label="Mode"
                    value={sending.dry_run ? "Dry run" : "Live"}
                  />
                </div>
                {sending.remaining === 0 && (
                  <p className="small faint mt">
                    The budget for today is spent. Sending resumes automatically at the next
                    UTC day boundary — raising the cap mid-ramp is what gets domains filtered.
                  </p>
                )}
              </>
            )}
          </div>

          {/* ---------------------------------------------- configuration */}
          {config && (
            <div className="grid grid-2">
              <div className="card">
                <h2>Identity</h2>
                <KeyValue label="Company" value={config.company.name} />
                <KeyValue
                  label="Website"
                  value={
                    config.company.website ? (
                      <a href={config.company.website} target="_blank" rel="noreferrer">
                        {config.company.website}
                      </a>
                    ) : "—"
                  }
                />
                <KeyValue label="Sender name" value={config.sender.name} />
                <KeyValue label="Sender email" value={<span className="mono">{config.sender.email}</span>} />
                <KeyValue label="Environment" value={config.env} />
              </div>

              <div className="card">
                <h2>Sending policy</h2>
                <KeyValue label="Daily cap" value={`${config.daily_send_cap} emails`} />
                <KeyValue label="Minimum gap between sends" value={`${config.min_seconds_between_sends}s`} />
                <KeyValue label="Max leads per domain per day" value={config.max_per_domain_per_day} />
                <KeyValue
                  label="Send window (lead's local time)"
                  value={`${hourLabel(config.send_window[0])} – ${hourLabel(config.send_window[1])}`}
                />
                <KeyValue label="Weekends" value={config.send_on_weekends ? "Allowed" : "Never"} />
                <KeyValue label="Warm-up ramp" value={config.warmup_enabled ? "On" : "Off"} />
              </div>

              <div className="card">
                <h2>Follow-ups &amp; approval</h2>
                <KeyValue label="Follow-ups" value={config.followup_enabled ? "Enabled" : "Disabled"} />
                <KeyValue label="Maximum follow-ups" value={config.max_followups} />
                <KeyValue
                  label="Delays"
                  value={
                    config.followup_delays_days.length
                      ? config.followup_delays_days.map((d) => `${d}d`).join(" → ")
                      : "—"
                  }
                />
                <KeyValue
                  label="Manual approval"
                  value={config.require_manual_approval ? "Required before any send" : "Not required"}
                />
                <KeyValue
                  label="AI reply classification"
                  value={config.ai_classify_replies ? "On" : "Off"}
                />
              </div>

              <div className="card">
                <h2>Providers</h2>
                {Object.entries(config.integrations).map(([key, enabled]) => (
                  <Toggle key={key} on={enabled} label={key.replace(/_/g, " ")} />
                ))}
                <Toggle on={config.google_places_enabled} label="google places discovery" />
              </div>

              <div className="card" style={{ gridColumn: "1 / -1" }}>
                <h2>Blocked countries</h2>
                <p className="small faint" style={{ marginTop: 0 }}>
                  Unsolicited B2B email in these jurisdictions needs prior consent, so leads
                  there are never auto-sent regardless of status.
                </p>
                {config.blocked_countries.length ? (
                  <div className="chips">
                    {config.blocked_countries.map((code) => (
                      <span key={code} className="badge badge-grey mono">{code}</span>
                    ))}
                  </div>
                ) : (
                  <Empty>No countries are blocked.</Empty>
                )}
              </div>
            </div>
          )}

          {/* -------------------------------------------- suppressions ---- */}
          <div className="card">
            <div className="spread mb">
              <h2 style={{ margin: 0 }}>Suppression list</h2>
              <span className="badge badge-grey">
                {suppressions ? `${suppressions.length} entr${suppressions.length === 1 ? "y" : "ies"}` : "—"}
              </span>
            </div>
            <p className="small faint" style={{ marginTop: 0 }}>
              Addresses and domains here are excluded from every send, permanently and
              across all campaigns. Unsubscribes and hard bounces land here automatically;
              add entries by hand when someone asks off-channel.
            </p>

            <form onSubmit={addSuppression} className="mt">
              <div className="grid" style={{ gridTemplateColumns: "140px 1fr 1fr auto", alignItems: "end" }}>
                <div className="field" style={{ marginBottom: 0 }}>
                  <label htmlFor="sup-kind">Kind</label>
                  <select
                    id="sup-kind"
                    value={form.kind}
                    onChange={(e) =>
                      setForm({ ...form, kind: e.target.value as SuppressionInput["kind"] })}
                  >
                    <option value="email">Email</option>
                    <option value="domain">Domain</option>
                  </select>
                </div>
                <div className="field" style={{ marginBottom: 0 }}>
                  <label htmlFor="sup-value">
                    {form.kind === "email" ? "Email address" : "Domain"}
                  </label>
                  <input
                    id="sup-value"
                    className="mono"
                    value={form.value}
                    placeholder={form.kind === "email" ? "person@example.com" : "example.com"}
                    onChange={(e) => setForm({ ...form, value: e.target.value })}
                  />
                </div>
                <div className="field" style={{ marginBottom: 0 }}>
                  <label htmlFor="sup-reason">Reason</label>
                  <input
                    id="sup-reason"
                    value={form.reason}
                    placeholder="manual"
                    onChange={(e) => setForm({ ...form, reason: e.target.value })}
                  />
                </div>
                <button type="submit" className="btn-primary" disabled={adding}>
                  {adding ? "Adding…" : "Add"}
                </button>
              </div>
              {formError && (
                <p className="small test-result-err mt" style={{ marginBottom: 0 }}>{formError}</p>
              )}
            </form>

            <div className="table-wrap mt">
              {!suppressions ? (
                <Loading />
              ) : suppressions.length === 0 ? (
                <Empty>
                  Nothing is suppressed yet. Unsubscribes, bounces and manual blocks will
                  appear here.
                </Empty>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Kind</th>
                      <th>Value</th>
                      <th>Reason</th>
                      <th>Added</th>
                      <th className="right">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {suppressions.map((entry) => (
                      <tr key={entry.id}>
                        <td>
                          <span className={`badge badge-${entry.kind === "domain" ? "violet" : "grey"}`}>
                            {entry.kind}
                          </span>
                        </td>
                        <td className="mono">{entry.value}</td>
                        <td className="dim">{entry.reason}</td>
                        <td className="nowrap dim">{formatDate(entry.created_at)}</td>
                        <td className="right">
                          <button
                            className="btn-sm btn-danger"
                            onClick={() => removeSuppression(entry)}
                            disabled={removingId === entry.id}
                          >
                            {removingId === entry.id ? "Removing…" : "Remove"}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            {suppressions && suppressions.length >= 500 && (
              <p className="small faint mt">Showing the 500 most recent entries.</p>
            )}
          </div>

          {/* ----------------------------------------- connection tests ---- */}
          <div className="card">
            <h2>Connection tests</h2>
            <p className="small faint" style={{ marginTop: 0 }}>
              Each test exercises the real client with your real credentials. The email test
              honours <strong>DRY RUN</strong> exactly like a campaign send does, so it will
              not deliver anything while dry run is on.
            </p>

            <div className="test-row">
              <div className="test-meta">
                <div className="test-name">SMTP</div>
                <div className="small faint">Sends a short test message to an address you choose.</div>
              </div>
              <input
                className="mono"
                style={{ width: 260 }}
                type="email"
                value={testEmail}
                placeholder="you@yourcompany.com"
                aria-label="Test email destination"
                onChange={(e) => setTestEmail(e.target.value)}
              />
              <button
                onClick={runEmailTest}
                disabled={tests.email.status === "pending" || !health?.smtp_configured}
              >
                {tests.email.status === "pending" ? "Sending…" : "Send test email"}
              </button>
              <TestResult state={tests.email} />
              {!health?.smtp_configured && (
                <div className="test-result faint">SMTP_HOST is not set — nothing to test.</div>
              )}
            </div>

            <div className="test-row">
              <div className="test-meta">
                <div className="test-name">Telegram</div>
                <div className="small faint">Posts a confirmation message to your configured chat.</div>
              </div>
              <button
                onClick={runTelegramTest}
                disabled={tests.telegram.status === "pending" || !health?.telegram_configured}
              >
                {tests.telegram.status === "pending" ? "Sending…" : "Send test message"}
              </button>
              <TestResult state={tests.telegram} />
              {!health?.telegram_configured && (
                <div className="test-result faint">
                  TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are not set — nothing to test.
                </div>
              )}
            </div>

            <div className="test-row">
              <div className="test-meta">
                <div className="test-name">Groq</div>
                <div className="small faint">Classifies a sample reply end to end.</div>
              </div>
              <button
                onClick={runGroqTest}
                disabled={tests.groq.status === "pending" || !health?.groq_configured}
              >
                {tests.groq.status === "pending" ? "Classifying…" : "Run classification"}
              </button>
              <TestResult state={tests.groq} />
              {!health?.groq_configured && (
                <div className="test-result faint">GROQ_API_KEY is not set — nothing to test.</div>
              )}
            </div>
          </div>
        </div>
      )}
    </Shell>
  );
}

function TestResult({ state }: { state: TestState }) {
  if (state.status === "idle") return null;
  const tone =
    state.status === "ok" ? "ok" : state.status === "error" ? "err" : "pending";
  return (
    <div className={`test-result test-result-${tone}`}>
      {state.status === "pending" && <span className="spinner" style={{ marginRight: 8 }} />}
      {state.status === "ok" && "✓ "}
      {state.status === "error" && "✕ "}
      {state.message}
    </div>
  );
}
