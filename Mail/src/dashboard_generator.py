"""
Interactive Global Command Center Dashboard Generator.
Builds standalone dark-mode visual interface with international market metrics and live CRM pipeline.
"""
import json
import datetime
from pathlib import Path
from src.crm import CRMDatabase
from src.analytics import SalesAnalytics
from src.config import DASHBOARD_HTML_PATH, TARGET_REVENUE

class DashboardGenerator:
    def __init__(self, crm: CRMDatabase):
        self.crm = crm
        self.analytics = SalesAnalytics(crm)

    def generate_html(self, output_path: Path = DASHBOARD_HTML_PATH) -> str:
        metrics = self.analytics.generate_pipeline_metrics()
        leads = self.crm.get_all_leads()
        inbox_msgs = self.crm.get_inbox_messages()
        outreach_logs = self.crm.get_outreach_history()

        lead_rows = ""
        for l in sorted(leads, key=lambda x: (x["stage"] != "BOUNCED", x["deal_value"] * x["probability"]), reverse=True):
            status_badge = "bg-emerald-500/20 text-emerald-400 border-emerald-500/30"
            if l["stage"] == "BOUNCED":
                status_badge = "bg-rose-500/20 text-rose-400 border-rose-500/30"
            elif "SENT" in l["stage"]:
                status_badge = "bg-blue-500/20 text-blue-400 border-blue-500/30"
            elif "HOT" in l["stage"]:
                status_badge = "bg-amber-500/20 text-amber-400 border-amber-500/30"

            country = l.get("country", "United States")
            lead_rows += f"""
            <tr class="border-b border-slate-800/60 hover:bg-slate-800/40 transition">
                <td class="py-3.5 px-4 font-semibold text-white">{l['business']}</td>
                <td class="py-3.5 px-4 text-slate-400">{country} <span class="text-xs text-slate-500">({l['city']})</span></td>
                <td class="py-3.5 px-4 text-slate-300 font-mono text-sm">{l['email']}</td>
                <td class="py-3.5 px-4 text-slate-400">{l['industry']}</td>
                <td class="py-3.5 px-4 font-semibold text-indigo-300">${l['deal_value']:,.2f}</td>
                <td class="py-3.5 px-4">
                    <span class="px-2.5 py-1 rounded-full text-xs font-medium border {status_badge}">{l['stage']}</span>
                </td>
                <td class="py-3.5 px-4 text-slate-400 text-sm">{int(l['probability']*100)}%</td>
            </tr>
            """

        msg_rows = ""
        for m in sorted(inbox_msgs, key=lambda x: x["received_at"], reverse=True)[:8]:
            intent_color = "text-amber-400 bg-amber-500/10 border-amber-500/30" if m["intent"] in ["HOT_LEAD", "PRICING_REQUEST", "MEETING_REQUEST"] else "text-slate-400 bg-slate-800"
            msg_rows += f"""
            <div class="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800/80 hover:border-slate-700 transition">
                <div class="flex items-center justify-between mb-1.5">
                    <span class="text-sm font-semibold text-white">{m['sender_email']}</span>
                    <span class="text-xs px-2 py-0.5 rounded-md border {intent_color}">{m['intent']}</span>
                </div>
                <div class="text-xs text-slate-400 font-medium mb-1">{m['subject']}</div>
                <div class="text-xs text-slate-500 line-clamp-2">{m['body']}</div>
            </div>
            """

        countries_pills = "".join([f'<span class="px-3 py-1 bg-slate-800 text-indigo-300 text-xs font-semibold rounded-full border border-indigo-500/20">{k}: {v} leads</span>' for k,v in metrics["geographic_distribution"].items()])

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Autonomous Global AI Sales Operations Center</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        body {{ font-family: 'Plus Jakarta Sans', sans-serif; }}
        code, pre, .font-mono {{ font-family: 'JetBrains Mono', monospace; }}
    </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen p-6 md:p-10 antialiased">
    <div class="max-w-7xl mx-auto space-y-8">
        
        <!-- Header -->
        <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-slate-800">
            <div>
                <div class="flex items-center gap-3">
                    <div class="h-3 w-3 rounded-full bg-emerald-500 animate-ping"></div>
                    <span class="text-xs font-bold uppercase tracking-wider text-emerald-400">24/7 Production Daemon Active</span>
                </div>
                <h1 class="text-3xl font-extrabold tracking-tight mt-1 text-white">Global AI Sales & Operations Command Center</h1>
                <p class="text-sm text-slate-400 mt-0.5">Monitoring account: <span class="font-mono text-indigo-400">ksvdevlopers@gmail.com</span> | Target: <span class="font-bold text-white">${TARGET_REVENUE:,.2f} KPI</span></p>
            </div>
            <div class="flex items-center gap-3">
                <div class="text-right">
                    <div class="text-xs text-slate-400">Last Synced</div>
                    <div class="text-sm font-mono text-slate-300">{datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M:%S UTC')}</div>
                </div>
            </div>
        </div>

        <!-- Geographic Markets Banner -->
        <div class="flex flex-wrap items-center gap-2.5 p-4 rounded-2xl bg-slate-900/80 border border-slate-800">
            <span class="text-xs font-bold text-slate-400 uppercase tracking-wider mr-2">🌍 International Footprint:</span>
            {countries_pills}
        </div>

        <!-- KPI Metric Cards -->
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            <div class="p-6 rounded-2xl bg-slate-900/90 border border-slate-800 hover:border-indigo-500/50 transition">
                <div class="text-xs font-semibold uppercase tracking-wider text-slate-400">Active Weighted Pipeline</div>
                <div class="text-3xl font-extrabold text-white mt-2">${metrics['weighted_pipeline']:,.2f}</div>
                <div class="text-xs text-emerald-400 font-semibold mt-2">↑ {metrics['projected_attainment_pct']}% of $1,000 KPI</div>
            </div>
            <div class="p-6 rounded-2xl bg-slate-900/90 border border-slate-800 hover:border-indigo-500/50 transition">
                <div class="text-xs font-semibold uppercase tracking-wider text-slate-400">Total Valid Deliverable Leads</div>
                <div class="text-3xl font-extrabold text-white mt-2">{metrics['counts']['valid_deliverable_leads']}</div>
                <div class="text-xs text-indigo-400 font-semibold mt-2">Across US, UK, Canada, Australia</div>
            </div>
            <div class="p-6 rounded-2xl bg-slate-900/90 border border-slate-800 hover:border-indigo-500/50 transition">
                <div class="text-xs font-semibold uppercase tracking-wider text-slate-400">Outbound Transmitted</div>
                <div class="text-3xl font-extrabold text-white mt-2">{metrics['counts']['total_emails_sent']}</div>
                <div class="text-xs text-blue-400 font-semibold mt-2">Live Google SMTP Verified</div>
            </div>
            <div class="p-6 rounded-2xl bg-slate-900/90 border border-slate-800 hover:border-indigo-500/50 transition">
                <div class="text-xs font-semibold uppercase tracking-wider text-slate-400">24/7 IMAP Replies Tracked</div>
                <div class="text-3xl font-extrabold text-white mt-2">{metrics['counts']['total_replies_received']}</div>
                <div class="text-xs text-amber-400 font-semibold mt-2">NLP Intent Engine Active</div>
            </div>
        </div>

        <!-- Main Content Split -->
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
            <!-- Left 2 Cols: Leads Table -->
            <div class="lg:col-span-2 rounded-2xl bg-slate-900/90 border border-slate-800 overflow-hidden">
                <div class="p-5 border-b border-slate-800 flex items-center justify-between">
                    <h2 class="text-base font-bold text-white">Global CRM Directory & Pipeline</h2>
                    <span class="text-xs text-slate-400">Total: {len(leads)} leads</span>
                </div>
                <div class="overflow-x-auto">
                    <table class="w-full text-left text-sm">
                        <thead class="bg-slate-950/60 text-xs font-semibold uppercase text-slate-400 border-b border-slate-800">
                            <tr>
                                <th class="py-3 px-4">Business</th>
                                <th class="py-3 px-4">Country / City</th>
                                <th class="py-3 px-4">Email</th>
                                <th class="py-3 px-4">Industry</th>
                                <th class="py-3 px-4">Deal</th>
                                <th class="py-3 px-4">Stage</th>
                                <th class="py-3 px-4">Prob</th>
                            </tr>
                        </thead>
                        <tbody>
                            {lead_rows}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Right 1 Col: Live Incoming Messages -->
            <div class="rounded-2xl bg-slate-900/90 border border-slate-800 p-5 space-y-4">
                <div class="flex items-center justify-between border-b border-slate-800 pb-3">
                    <h2 class="text-base font-bold text-white">Live Inbox & Reply Stream</h2>
                    <span class="text-xs text-emerald-400 font-semibold">● Polling (30s)</span>
                </div>
                <div class="space-y-3 max-h-[600px] overflow-y-auto">
                    {msg_rows if msg_rows else '<div class="text-slate-500 text-xs text-center py-8">Monitoring inbox for incoming prospect replies...</div>'}
                </div>
            </div>
        </div>

    </div>
</body>
</html>
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return str(output_path)

if __name__ == "__main__":
    crm = CRMDatabase()
    gen = DashboardGenerator(crm)
    path = gen.generate_html()
    print(f"Generated standalone interactive dashboard at {path}")
