"use client";

import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { Banner, Loading } from "@/components/ui";
import { get, post, put } from "@/lib/api";
import type { Campaign } from "@/lib/types";

const VARIABLES = [
  "business_name", "contact_name", "category_label", "city", "country",
  "presence_line", "sender_name", "company_name", "company_website",
  "calendar_link", "unsubscribe_url",
];

const BLANK = {
  name: "", subject_template: "", body_template: "",
  followup_subject_template: "", followup_body_template: "",
  language: "en", is_active: true, daily_cap: null as number | null,
};

export default function CampaignsPage() {
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);
  const [selectedId, setSelectedId] = useState<number | "new" | null>(null);
  const [form, setForm] = useState({ ...BLANK });
  const [preview, setPreview] = useState<{ subject: string; text: string } | null>(null);
  const [previewStep, setPreviewStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const rows = await get<Campaign[]>("/api/campaigns");
      setCampaigns(rows);
      if (selectedId === null && rows.length) select(rows[0]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load campaigns");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function select(campaign: Campaign) {
    setSelectedId(campaign.id);
    setForm({
      name: campaign.name,
      subject_template: campaign.subject_template,
      body_template: campaign.body_template,
      followup_subject_template: campaign.followup_subject_template ?? "",
      followup_body_template: campaign.followup_body_template ?? "",
      language: campaign.language,
      is_active: campaign.is_active,
      daily_cap: campaign.daily_cap,
    });
    setPreview(null);
    setNotice(null);
  }

  async function save() {
    setBusy(true);
    setError(null);
    const payload = {
      ...form,
      followup_subject_template: form.followup_subject_template || null,
      followup_body_template: form.followup_body_template || null,
    };
    try {
      if (selectedId === "new" || selectedId === null) {
        const created = await post<Campaign>("/api/campaigns", payload);
        setNotice("Campaign created");
        setSelectedId(created.id);
      } else {
        await put(`/api/campaigns/${selectedId}`, payload);
        setNotice("Campaign saved");
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  async function runPreview(step: number) {
    setPreviewStep(step);
    setError(null);
    try {
      setPreview(await post<{ subject: string; text: string }>("/api/campaigns/preview", {
        campaign_id: typeof selectedId === "number" ? selectedId : null, step,
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Preview failed");
    }
  }

  return (
    <Shell>
      <div className="page-head">
        <div>
          <h1>Campaigns</h1>
          <p className="subtitle">
            The words you send. Templates are Jinja — an unknown variable is rejected
            on save, not discovered mid-send.
          </p>
        </div>
        <button onClick={() => { setSelectedId("new"); setForm({ ...BLANK }); setPreview(null); }}>
          New campaign
        </button>
      </div>

      {error && <Banner kind="error">{error}</Banner>}
      {notice && <Banner kind="ok">{notice}</Banner>}

      {!campaigns ? (
        <Loading />
      ) : (
        <div className="grid" style={{ gridTemplateColumns: "220px 1fr", alignItems: "start" }}>
          <div className="card">
            <h3>All campaigns</h3>
            {campaigns.map((campaign) => (
              <button key={campaign.id}
                      className={`btn-sm ${selectedId === campaign.id ? "btn-primary" : ""}`}
                      style={{ width: "100%", marginBottom: 6, textAlign: "left" }}
                      onClick={() => select(campaign)}>
                {campaign.name}
              </button>
            ))}
          </div>

          <div className="stack">
            <div className="card">
              <div className="grid grid-2">
                <div className="field">
                  <label htmlFor="name">Name</label>
                  <input id="name" value={form.name}
                         onChange={(e) => setForm({ ...form, name: e.target.value })} />
                </div>
                <div className="field">
                  <label htmlFor="cap">Daily cap for this campaign (optional)</label>
                  <input id="cap" type="number" min={1} value={form.daily_cap ?? ""}
                         onChange={(e) => setForm({
                           ...form,
                           daily_cap: e.target.value ? Number(e.target.value) : null,
                         })} />
                </div>
              </div>

              <div className="field">
                <label htmlFor="subject">First email — subject</label>
                <input id="subject" className="mono" value={form.subject_template}
                       onChange={(e) => setForm({ ...form, subject_template: e.target.value })} />
              </div>
              <div className="field">
                <label htmlFor="body">First email — body</label>
                <textarea id="body" rows={14} value={form.body_template}
                          onChange={(e) => setForm({ ...form, body_template: e.target.value })} />
              </div>

              <div className="field">
                <label htmlFor="fsubject">Follow-up — subject</label>
                <input id="fsubject" className="mono" value={form.followup_subject_template}
                       onChange={(e) =>
                         setForm({ ...form, followup_subject_template: e.target.value })} />
              </div>
              <div className="field">
                <label htmlFor="fbody">Follow-up — body</label>
                <textarea id="fbody" rows={10} value={form.followup_body_template}
                          onChange={(e) =>
                            setForm({ ...form, followup_body_template: e.target.value })} />
              </div>

              <div className="row">
                <label className="row" style={{ marginBottom: 0 }}>
                  <input type="checkbox" style={{ width: 15 }} checked={form.is_active}
                         onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
                  <span>Active</span>
                </label>
                <div style={{ flex: 1 }} />
                <button onClick={() => runPreview(0)}>Preview first email</button>
                <button onClick={() => runPreview(1)}>Preview follow-up</button>
                <button className="btn-primary" onClick={save} disabled={busy}>
                  {busy ? "Saving…" : "Save"}
                </button>
              </div>

              <p className="small faint mt">
                Available variables:{" "}
                {VARIABLES.map((v) => <code key={v} className="mono">{`{{ ${v} }}`} </code>)}
                <br />
                An unsubscribe link and your postal address are appended automatically —
                both are legally required, so they are not editable here.
              </p>
            </div>

            {preview && (
              <div className="card">
                <h2>Preview — {previewStep === 0 ? "first email" : "follow-up"}</h2>
                <div className="msg-block">
                  <strong>{preview.subject}</strong>
                  <div className="msg-body" style={{ maxHeight: "none" }}>{preview.text}</div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </Shell>
  );
}
