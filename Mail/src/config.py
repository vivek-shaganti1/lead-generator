"""
System Configuration & Constants for Autonomous Sales & Gmail Outreach Agent.
"""
import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"
DB_PATH = DATA_DIR / "crm.db"
MASTER_CSV_PATH = DATA_DIR / "crm_leads_master.csv"
GLOBAL_CSV_PATH = DATA_DIR / "global_crm_master.csv"
PIPELINE_METRICS_PATH = DATA_DIR / "pipeline_metrics.json"
REPORT_MD_PATH = DATA_DIR / "sales_intelligence_report.md"
DASHBOARD_HTML_PATH = STATIC_DIR / "dashboard.html"

# Target Revenue KPI
REVENUE_TARGET = 1000.0  # $1,000 revenue target as required by prompt
TARGET_REVENUE = 1000.0
DEFAULT_PACKAGE_STARTER = 450.0
DEFAULT_PACKAGE_GROWTH = 600.0
DEFAULT_PACKAGE_PRO = 850.0
DEFAULT_PACKAGE_ENTERPRISE = 1000.0

# Gmail Configuration
GMAIL_USER = os.getenv("GMAIL_USER", os.getenv("SMTP_USER", "ksvdevlopers@gmail.com"))
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", os.getenv("SMTP_PASSWORD", ""))
GMAIL_SMTP_SERVER = "smtp.gmail.com"
GMAIL_SMTP_PORT = 465
GMAIL_IMAP_SERVER = "imap.gmail.com"
GMAIL_IMAP_PORT = 993

# Sender Profile
SENDER_NAME = "KSV Web & AI Solutions Team"
SENDER_EMAIL = GMAIL_USER

# Cadence Intervals (in days)
FOLLOWUP_1_DAYS = 3
FOLLOWUP_2_DAYS = 7
FOLLOWUP_FINAL_DAYS = 14

# Rate Limits (Safe sending rules)
MAX_EMAILS_PER_BATCH = 25
DELAY_BETWEEN_EMAILS_SEC = 2
