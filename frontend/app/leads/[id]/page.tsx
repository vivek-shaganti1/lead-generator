"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import {
  Banner, Empty, Loading, ReplyBadge, StatusBadge, formatDate,
} from "@/components/ui";
import { get, patch, post } from "@/lib/api";
import type { InboundMessage, Lead } from "@/lib/types";

export default function LeadDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;

  const [lead, setLead] = useState<Lead | null>(null);
  const [replies, setReplies] = useState<InboundMessage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [contactName, setContactName] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const detail = await get<Lead>(`/api/leads/${id}`);
      setLead(detail);
      setNotes(detail.notes ?? "");
      setContactName(detail.contact_name ?? "");
      setReplies(await get<InboundMessage[]>(`/api/leads/${id}/replies`));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load this lead");
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  async function update(body: Record<string, unknown>, message: string) {
    setBusy(true);
    setError(null);
    try {
      await patch(`/api/leads/${id}`, body);
      setNotice(message);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    } finally {
      setBusy(false);
    }
  }

  async function sendNow(force: boolean) {
    setBusy(true);
    setError(null);
    try {
      await post(`/api/leads/${id}/send?force=${force}`);
      setNotice(force ? "Sent (pacing bypassed)" : "Sent");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Send failed");
    } finally {
      setBusy(false);
    }
  }

  if (!lead) {
    return (
      <Shell>
        {error ? <Banner kind="error">{error}</Banner> : <Loading />}
      </Shell>
    );
  }

  const business = lead.business;

  return (
    <Shell>
      <div className="page-head">
        <div>
          <p className="small"><Link href="/leads">← All leads</Link></p>
          <h1>{business.name}</h1>
          <div className="row">
            <StatusBadge status={lead.status} />
            <span className="small dim">Score {lead.score.toFixed(0)}</span>
            {lead.approved
              ? <span className="badge badge-green">APPROVED</span>
              : <span className="badge badge-amber">NOT APPROVED</span>}
          </div>
        </div>
        <div className="row">
          {!lead.approved && (
            <button className="btn-primary" disabled={busy}
                    onClick={() => update({ approved: true }, "Lead approved")}>
              Approve
            </button>
          )}
          {lead.approved && (
            <button disabled={busy}
                    onClick={() => update({ approved: false }, "Approval withdrawn")}>
              Withdraw approval
            </button>
          )}
          <button disabled={busy} onClick={() => sendNow(false)}>Send next email</button>
          <button className="btn-sm" disabled={busy} onClick={() => sendNow(true)}
                  title="Skips pacing rules. Compliance checks still apply.">
            Force send
          </button>
        </div>
      </div>

      {error && <Banner kind="error">{error}</Banner>}
      {notice && <Banner kind="ok">{notice}</Banner>}
      {lead.block_reason && <Banner kind="warn">Blocked: {lead.block_reason}</Banner>}

      <div className="grid grid-2">
        <div className="stack">
          <div className="card">
            <h2>Business</h2>
            <table>
              <tbody>
                <Row label="Email"><span className="mono">{lead.email}</span></Row>
                <Row label="Email source">
                  {lead.email_source} · confidence {(lead.email_confidence * 100).toFixed(0)}%
                  {lead.is_role_account && " · role account"}
                </Row>
                <Row label="Phone">{business.phone ?? "—"}</Row>
                <Row label="Category">{business.category?.replace(/_/g, " ") ?? "—"}</Row>
                <Row label="Address">
                  {[business.address, business.city, business.region, business.country_code]
                    .filter(Boolean).join(", ") || "—"}
                </Row>
                <Row label="Timezone">{business.timezone_name ?? "—"}</Row>
                <Row label="Website">
                  {business.website ? (
                    <a href={business.website} target="_blank" rel="noreferrer noopener">
                      {business.website}
                    </a>
                  ) : (
                    <span className="badge badge-blue">NONE FOUND</span>
                  )}
                  {business.website_alive === false && (
                    <span className="badge badge-amber" style={{ marginLeft: 8 }}>NOT LOADING</span>
                  )}
                </Row>
                <Row label="Source">{business.source}</Row>
                {business.lat !== null && business.lon !== null && (
                  <Row label="Map">
                    <a href={`https://www.openstreetmap.org/?mlat=${business.lat}&mlon=${business.lon}#map=18/${business.lat}/${business.lon}`}
                       target="_blank" rel="noreferrer noopener">
                      Open in OpenStreetMap
                    </a>
                  </Row>
                )}
                <Row label="Follow-ups sent">{lead.followups_sent}</Row>
                <Row label="Next action">{formatDate(lead.next_action_at)}</Row>
              </tbody>
            </table>
          </div>

          <div className="card">
            <h2>Your notes</h2>
            <div className="field">
              <label htmlFor="contact">Contact name (used in the greeting)</label>
              <input id="contact" value={contactName}
                     onChange={(e) => setContactName(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="notes">Notes</label>
              <textarea id="notes" rows={4} value={notes}
                        onChange={(e) => setNotes(e.target.value)} />
            </div>
            <div className="row">
              <button className="btn-primary" disabled={busy}
                      onClick={() => update({ notes, contact_name: contactName || null },
                                            "Saved")}>
                Save
              </button>
              {lead.status !== "WON" && (
                <button disabled={busy}
                        onClick={() => update({ status: "WON" }, "Marked as won 🎉")}>
                  Mark as won
                </button>
              )}
            </div>
          </div>
        </div>

        <div className="stack">
          <div className="card">
            <h2>Replies ({replies.length})</h2>
            {replies.length === 0 ? (
              <Empty>No replies yet.</Empty>
            ) : (
              replies.map((reply) => (
                <div className="msg-block" key={reply.id}>
                  <div className="spread">
                    <div>
                      <strong className="small">{reply.subject || "(no subject)"}</strong>
                      <div className="small faint mono">{reply.from_email}</div>
                    </div>
                    <div className="right">
                      <ReplyBadge value={reply.classification} />
                      <div className="small faint">
                        {reply.classifier} · {(reply.confidence * 100).toFixed(0)}%
                      </div>
                    </div>
                  </div>
                  {reply.summary && (
                    <div className="small" style={{ marginTop: 8, color: "var(--accent)" }}>
                      🤖 {reply.summary}
                    </div>
                  )}
                  <div className="msg-body">{reply.body_text}</div>
                  <div className="small faint mt">{formatDate(reply.received_at)}</div>
                </div>
              ))
            )}
          </div>

          <div className="card">
            <h2>Sent messages ({lead.messages?.length ?? 0})</h2>
            {!lead.messages?.length ? (
              <Empty>Nothing sent yet.</Empty>
            ) : (
              [...lead.messages]
                .sort((a, b) => a.step - b.step)
                .map((message) => (
                  <div className="msg-block" key={message.id}>
                    <div className="spread">
                      <div>
                        <strong className="small">{message.subject}</strong>
                        <div className="small faint">
                          {message.step === 0 ? "First email" : `Follow-up ${message.step}`}
                          {" · "}{formatDate(message.sent_at)}
                        </div>
                      </div>
                      <div className="right">
                        <span className={`badge badge-${
                          message.status === "SENT" ? "green"
                            : message.status === "FAILED" || message.status === "BOUNCED"
                              ? "red" : "grey"}`}>
                          {message.status}
                        </span>
                        {message.dry_run && (
                          <div><span className="badge badge-amber">DRY RUN</span></div>
                        )}
                      </div>
                    </div>
                    {message.error && (
                      <div className="small" style={{ color: "var(--red)", marginTop: 6 }}>
                        {message.error}
                      </div>
                    )}
                    {message.opened_at && (
                      <div className="small dim" style={{ marginTop: 6 }}>
                        Opened {message.open_count}× · first {formatDate(message.opened_at)}
                      </div>
                    )}
                    <div className="msg-body">{message.body_text}</div>
                  </div>
                ))
            )}
          </div>
        </div>
      </div>
    </Shell>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <tr>
      <th style={{ width: 150, textTransform: "none", letterSpacing: 0, fontSize: 12.5 }}>
        {label}
      </th>
      <td>{children}</td>
    </tr>
  );
}
