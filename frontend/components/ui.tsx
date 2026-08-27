"use client";

import type { LeadStatus, ReplyClass } from "@/lib/types";

export function Tile({
  label, value, sub, tone,
}: { label: string; value: React.ReactNode; sub?: string; tone?: string }) {
  return (
    <div className="card">
      <div className="tile-label">{label}</div>
      <div className="tile-value" style={tone ? { color: `var(--${tone})` } : undefined}>
        {value}
      </div>
      {sub && <div className="tile-sub">{sub}</div>}
    </div>
  );
}

const STATUS_TONE: Record<LeadStatus, string> = {
  NEW: "grey",
  NEEDS_APPROVAL: "amber",
  READY: "blue",
  QUEUED: "blue",
  CONTACTED: "violet",
  FOLLOWED_UP: "violet",
  REPLIED: "amber",
  POSITIVE: "green",
  NEUTRAL: "grey",
  NEGATIVE: "red",
  UNSUBSCRIBED: "red",
  BOUNCED: "red",
  DO_NOT_CONTACT: "red",
  FAILED: "red",
  WON: "green",
};

const REPLY_TONE: Record<ReplyClass, string> = {
  POSITIVE: "green", NEGATIVE: "red", NEUTRAL: "grey", QUESTION: "amber",
  UNSUBSCRIBE: "red", AUTO_REPLY: "grey", BOUNCE: "red", UNKNOWN: "grey",
};

export function StatusBadge({ status }: { status: LeadStatus }) {
  return (
    <span className={`badge badge-${STATUS_TONE[status] ?? "grey"}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

export function ReplyBadge({ value }: { value: ReplyClass }) {
  return <span className={`badge badge-${REPLY_TONE[value] ?? "grey"}`}>{value}</span>;
}

export function Banner({ kind, children }: { kind: "warn" | "error" | "ok" | "info"; children: React.ReactNode }) {
  return <div className={`banner banner-${kind}`}>{children}</div>;
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Loading() {
  return (
    <div className="empty">
      <span className="spinner" />
    </div>
  );
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export function formatDay(value: string): string {
  const date = new Date(`${value}T00:00:00Z`);
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function pct(value: number): string {
  return `${value.toFixed(1)}%`;
}

/** A coloured dot plus label — used for per-dependency health readouts. */
export function StatusDot({
  ok, label, okText = "OK", badText = "Down", neutral,
}: {
  ok: boolean;
  label: string;
  okText?: string;
  badText?: string;
  /** Render "off" as a muted, non-alarming state (an unconfigured optional integration). */
  neutral?: boolean;
}) {
  const tone = ok ? "green" : neutral ? "grey" : "red";
  return (
    <div className="status-line">
      <span className={`status-dot status-dot-${tone}`} aria-hidden />
      <span className="status-label">{label}</span>
      <span className={`badge badge-${tone}`}>{ok ? okText : badText}</span>
    </div>
  );
}

/** Read-only label / value pair for configuration display. */
export function KeyValue({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="kv">
      <span className="kv-label">{label}</span>
      <span className="kv-value">{value}</span>
    </div>
  );
}

/** Horizontal usage meter. `tone` is a CSS custom-property name without the dashes. */
export function Meter({
  value, max, tone = "accent",
}: { value: number; max: number; tone?: string }) {
  const ratio = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="meter" role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={max}>
      <div className="meter-fill" style={{ width: `${ratio}%`, background: `var(--${tone})` }} />
    </div>
  );
}

export function Toggle({ on, label }: { on: boolean; label: string }) {
  return (
    <div className="status-line">
      <span className={`status-dot status-dot-${on ? "green" : "grey"}`} aria-hidden />
      <span className="status-label">{label}</span>
      <span className="small faint">{on ? "enabled" : "disabled"}</span>
    </div>
  );
}
