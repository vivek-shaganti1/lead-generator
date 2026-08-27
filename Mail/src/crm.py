"""
CRM Database Layer for Lead Lifecycle, Deal Tracking, and Pipeline Management.
"""
import sqlite3
import datetime
import csv
from typing import List, Dict, Any, Optional
from pathlib import Path
from src.config import DB_PATH, MASTER_CSV_PATH, DATA_DIR

class CRMDatabase:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initializes database schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Leads table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS leads (
                    id TEXT PRIMARY KEY,
                    campaign TEXT,
                    rank INTEGER,
                    business TEXT,
                    city TEXT,
                    state TEXT,
                    industry TEXT,
                    google_rating REAL,
                    reviews INTEGER,
                    website TEXT,
                    website_status TEXT,
                    followers INTEGER,
                    platform TEXT,
                    owner TEXT,
                    email TEXT,
                    phone TEXT,
                    instagram TEXT,
                    lead_score INTEGER,
                    deal_value REAL,
                    pitch_hook TEXT,
                    audit_notes TEXT,
                    status TEXT DEFAULT 'READY_FOR_OUTREACH',
                    stage TEXT DEFAULT 'UNCONTACTED',
                    probability REAL DEFAULT 0.15,
                    last_contact_date TEXT,
                    next_followup_date TEXT,
                    followup_count INTEGER DEFAULT 0,
                    created_at TEXT,
                    updated_at TEXT
                )
            ''')

            # Outreach logs
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS outreach_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lead_id TEXT,
                    campaign TEXT,
                    recipient_email TEXT,
                    subject TEXT,
                    body TEXT,
                    step_name TEXT,
                    status TEXT,
                    message_id TEXT,
                    sent_at TEXT,
                    FOREIGN KEY(lead_id) REFERENCES leads(id)
                )
            ''')

            # Inbox / replies table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS inbox_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lead_id TEXT,
                    sender_email TEXT,
                    subject TEXT,
                    body TEXT,
                    intent TEXT,
                    sentiment TEXT,
                    is_actionable INTEGER DEFAULT 1,
                    received_at TEXT,
                    classified_at TEXT,
                    FOREIGN KEY(lead_id) REFERENCES leads(id)
                )
            ''')
            conn.commit()

    def import_leads(self, leads: List[Dict[str, Any]]) -> int:
        """Upserts normalized leads into CRM."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        count = 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for lead in leads:
                cursor.execute('''
                    INSERT INTO leads (
                        id, campaign, rank, business, city, state, industry,
                        google_rating, reviews, website, website_status, followers,
                        platform, owner, email, phone, instagram, lead_score,
                        deal_value, pitch_hook, audit_notes, status, stage,
                        probability, created_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?
                    )
                    ON CONFLICT(id) DO UPDATE SET
                        lead_score=excluded.lead_score,
                        deal_value=excluded.deal_value,
                        pitch_hook=excluded.pitch_hook,
                        audit_notes=excluded.audit_notes,
                        updated_at=excluded.updated_at
                ''', (
                    lead['id'], lead['campaign'], lead.get('rank', 0), lead['business'],
                    lead.get('city', ''), lead.get('state', ''), lead.get('industry', ''),
                    lead.get('google_rating', 0.0), lead.get('reviews', 0), lead.get('website'),
                    lead.get('website_status', ''), lead.get('followers', 0),
                    lead.get('platform', ''), lead.get('owner', 'Business Owner'),
                    lead.get('email', ''), lead.get('phone', ''), lead.get('instagram'),
                    lead.get('lead_score', 70), lead.get('deal_value', 450.0),
                    lead.get('pitch_hook', ''), lead.get('audit_notes', ''),
                    lead.get('status', 'READY_FOR_OUTREACH'), lead.get('stage', 'UNCONTACTED'),
                    lead.get('probability', 0.15), now, now
                ))
                count += 1
            conn.commit()
        self.export_to_csv()
        return count

    def get_all_leads(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM leads ORDER BY lead_score DESC')
            return [dict(row) for row in cursor.fetchall()]

    def get_lead(self, lead_id: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM leads WHERE id = ?', (lead_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_lead_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM leads WHERE LOWER(email) = LOWER(?)', (email.strip(),))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_lead_stage(self, lead_id: str, stage: str, status: Optional[str] = None,
                          probability: Optional[float] = None, next_followup_date: Optional[str] = None):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            updates = ['stage = ?', 'updated_at = ?']
            params = [stage, now]
            
            if status:
                updates.append('status = ?')
                params.append(status)
            if probability is not None:
                updates.append('probability = ?')
                params.append(probability)
            if next_followup_date is not None:
                updates.append('next_followup_date = ?')
                params.append(next_followup_date)

            params.append(lead_id)
            cursor.execute(f'UPDATE leads SET {", ".join(updates)} WHERE id = ?', params)
            conn.commit()
        self.export_to_csv()

    def log_outreach(self, lead_id: str, campaign: str, recipient_email: str,
                     subject: str, body: str, step_name: str, status: str,
                     message_id: str = ''):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO outreach_logs (
                    lead_id, campaign, recipient_email, subject, body,
                    step_name, status, message_id, sent_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (lead_id, campaign, recipient_email, subject, body, step_name, status, message_id, now))
            
            # Update lead last_contact_date and followup_count
            cursor.execute('''
                UPDATE leads
                SET last_contact_date = ?,
                    followup_count = followup_count + 1,
                    status = 'CONTACTED',
                    updated_at = ?
                WHERE id = ?
            ''', (now, now, lead_id))
            conn.commit()
        self.export_to_csv()

    def log_inbox_message(self, lead_id: Optional[str], sender_email: str,
                          subject: str, body: str, intent: str,
                          sentiment: str, is_actionable: bool = True):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO inbox_messages (
                    lead_id, sender_email, subject, body,
                    intent, sentiment, is_actionable, received_at, classified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (lead_id, sender_email, subject, body, intent, sentiment, 1 if is_actionable else 0, now, now))
            conn.commit()

    def get_outreach_history(self, lead_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if lead_id:
                cursor.execute('SELECT * FROM outreach_logs WHERE lead_id = ? ORDER BY sent_at DESC', (lead_id,))
            else:
                cursor.execute('SELECT * FROM outreach_logs ORDER BY sent_at DESC')
            return [dict(row) for row in cursor.fetchall()]

    def get_inbox_messages(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM inbox_messages ORDER BY received_at DESC')
            return [dict(row) for row in cursor.fetchall()]

    def export_to_csv(self, file_path: Path = MASTER_CSV_PATH):
        """Exports full leads table to Master CSV."""
        leads = self.get_all_leads()
        if not leads:
            return
        file_path.parent.mkdir(parents=True, exist_ok=True)
        keys = leads[0].keys()
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            dict_writer = csv.DictWriter(f, fieldnames=keys)
            dict_writer.writeheader()
            dict_writer.writerows(leads)

if __name__ == '__main__':
    from src.data_importer import get_normalized_leads
    crm = CRMDatabase()
    leads = get_normalized_leads()
    count = crm.import_leads(leads)
    print(f'Successfully initialized CRM DB with {count} leads.')
