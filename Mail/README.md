# 🚀 Autonomous AI Sales & Gmail Operations Agent
### AI Cloud Sales, Outreach CRM, Lead Tracking & Revenue Optimization System ($1,000+ KPI Target)

---

## 📌 Executive Summary
An autonomous Sales Operations, CRM, and Gmail Outreach Agent built to orchestrate cold outreach campaigns, track incoming lead replies, detect sales opportunities, automate follow-up cadences, and manage deal flow to achieve and surpass the **$1,000+ Revenue Target**.

The agent is pre-loaded with **27 verified high-value local business leads** across 3 targeted campaigns:
1. **Campaign 1 (Gyms & Fitness Centers)**: 10 verified DFW facilities operating without an active website (The Train Station, GRINDHARD Elite, Reyes Boxing, Goss Fitness, Limitless Fitness, KRB Fitness, etc.).
2. **Campaign 2 (Salons & Barbershops)**: 10 top-rated salons (up to 1,607 Google reviews and 10.6K Instagram followers) without independent websites (El Barber Shop, AL HAYBA, Thakur Desi [2 locations], Crown & Blade, Royal Cut, etc.).
3. **Campaign 3 (Big Social & High Engagement)**: 7 verified high-following brands (up to 750K YouTube subscribers and 124K Instagram followers) with verified technical and conversion defects on their existing websites (Guins Excavating, Firepunk Diesel, Stiles Switch BBQ, Mum Foods, Onizuka Tattoo, Micklethwait BBQ, Whipped Bakery).

---

## 🏗️ System Architecture

```
/Users/vivekshaganti/Desktop/Projects/Mail/
├── data/
│   ├── raw_leads.json               # Cleaned & structured source leads
│   ├── crm.db                       # SQLite CRM Database (leads, outreach_logs, inbox_messages)
│   ├── crm_leads_master.csv         # Master exportable CRM spreadsheet
│   ├── pipeline_metrics.json        # Real-time revenue analytics & stage distributions
│   └── sales_intelligence_report.md # Executive business intelligence markdown report
├── src/
│   ├── config.py                    # Credentials, email configuration & revenue constants
│   ├── crm.py                       # CRM database layer, lifecycle tracking & stage updates
│   ├── data_importer.py             # Lead normalization & data ingestion
│   ├── copywriter.py                # Hyper-personalized cold email copy & 4-touch sequences
│   ├── gmail_client.py              # Gmail SMTP/IMAP client with resilient Simulation Fallback
│   ├── classifier.py                # Sales NLP reply classifier (Hot/Warm/Won/Lost/Unsub)
│   ├── followups.py                 # Multi-touch cadence engine (Days 3, 7, 14)
│   ├── analytics.py                 # Revenue calculation ($1,000 target pacing & weighted value)
│   └── dashboard_generator.py       # Standalone interactive dark-mode HTML dashboard generator
├── static/
│   └── dashboard.html               # Interactive CRM & Revenue Command Center UI
├── tests/
│   ├── test_crm.py                  # Database and lead scoring unit tests
│   ├── test_copywriter.py           # Email sequence generation unit tests
│   ├── test_classifier.py           # Reply intent classification unit tests
│   └── test_full_pipeline.py        # End-to-end integration and revenue calculation tests
├── agent.py                         # Unified CLI Command Center
├── requirements.txt                 # Python dependencies
└── README.md                        # Complete operations guide
```

---

## 🔑 Gmail Integration & Live Setup

### Important Note on Google Authentication:
Google discontinued standard password login on standard SMTP/IMAP since 2022. To enable **Live Gmail Sending & Real-Time Inbox Monitoring**, generate a **16-character Google App Password**:
1. Log into your Google Account: **`ksvdevlopers@gmail.com`**.
2. Go to **Security** > **2-Step Verification** (must be enabled).
3. Scroll to **App passwords** (or search "App passwords" in the Google account search bar).
4. Create a new app password named `SalesAgent` (produces a 16-character code like `abcd efgh ijkl mnop`).
5. Set environment variable:
   ```bash
   export GMAIL_USER="ksvdevlopers@gmail.com"
   export GMAIL_APP_PASSWORD="your-16-char-app-password"
   ```

> [!TIP]
> The agent comes equipped with an automatic **Dual-Mode Engine**. If running in dry-run, offline, or sandbox environments without active App Password credentials, it automatically activates the **High-Fidelity Simulation Engine**, allowing you to execute 100% of the workflow, dispatch test batches, classify simulated incoming replies, track weighted pipeline, and view live interactive dashboards without missing a beat.

---

## ⚡ CLI Command Center Usage

Run all actions via `python3 agent.py`:

```bash
# 1. Full Autonomous End-to-End Pipeline Execution:
python3 agent.py --action run-all

# 2. Test Gmail IMAP/SMTP Connection & Diagnostics:
python3 agent.py --action test-gmail

# 3. Ingest & Normalize Leads to CRM:
python3 agent.py --action import-leads

# 4. Dispatch Initial Outreach Pitch Emails:
python3 agent.py --action send-batch

# 5. Monitor Inbox, Fetch Replies & Classify Lead Intent:
python3 agent.py --action sync-inbox

# 6. Evaluate Cadence & Process Due Follow-Ups (Days 3, 7, 14):
python3 agent.py --action run-followups

# 7. Generate Revenue Intelligence & KPI Report:
python3 agent.py --action report

# 8. Render & Refresh Interactive HTML Dashboard:
python3 agent.py --action dashboard
```

---

## 📊 Revenue Acceleration Strategy ($1,000+ Target)

| Campaign | Total Leads | Avg Package | Total Pipeline | Strategy to Hit $1,000 |
|---|---|---|---|---|
| **1-Gyms** | 10 Leads | $425 | **$4,250.00** | Pitch local SEO + free trial class mobile booking funnels to capture walk-in and Instagram traffic. Closing **3 gyms = $1,350 (Goal Met)**. |
| **2-Salons** | 10 Leads | $430 | **$4,300.00** | Pitch commission-free direct booking to eliminate 3rd-party platform fees (Booksy). Closing **El Barber Shop ($500) + Thakur Desi ($600) = $1,100 (Goal Met)**. |
| **3-BigSocial** | 7 Leads | $714 | **$5,000.00** | Pitch high-impact website redesigns highlighting verified conversion bottlenecks. Closing **Guins Excavating ($850) + Firepunk Diesel ($850) = $1,700 (Goal Exceeded)**. |

---

## 🧪 Automated Test Suite

To run all 9 automated tests:
```bash
python3 -m unittest discover -s tests -p "test_*.py"
```
All tests verify CRM persistence, sequence copy integrity, NLP sentiment tagging, and revenue calculations.
