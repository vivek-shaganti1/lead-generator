import imaplib
import email
import os
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / 'backend'))
from app.config import settings

def main():
    mail = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
    mail.login(settings.imap_user, settings.imap_password)

    # 1. Get all sent emails in the last batch (Sept 4 / Sept 5)
    mail.select('"[Gmail]/Sent Mail"')
    _, data = mail.search(None, 'SINCE', '04-Sep-2026')
    sent_ids = data[0].split()

    sent_leads = []
    for msg_id in sent_ids:
        _, msg_data = mail.fetch(msg_id, '(BODY.PEEK[HEADER.FIELDS (TO SUBJECT DATE)])')
        msg = email.message_from_bytes(msg_data[0][1])
        to = msg.get('To', '').strip()
        subj = msg.get('Subject', '').strip()
        date = msg.get('Date', '').strip()
        if to and to.lower() != settings.imap_user.lower():
            # extract clean email
            m = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', to)
            clean_to = m.group(1).lower() if m else to.lower()
            sent_leads.append({'to': clean_to, 'subject': subj, 'date': date})

    print(f"Total Sent to prospects since Sep 4: {len(sent_leads)}")

    # 2. Get all bounce messages in INBOX
    mail.select('INBOX')
    _, data = mail.search(None, 'SINCE', '04-Sep-2026')
    inbox_ids = data[0].split()
    print(f"Total Inbox messages since Sep 4: {len(inbox_ids)}")

    bounced_addrs = set()
    genuine_replies = []

    # Fetch headers first to identify bounces vs replies
    for msg_id in inbox_ids:
        _, msg_data = mail.fetch(msg_id, '(RFC822)')
        msg = email.message_from_bytes(msg_data[0][1])
        frm = msg.get('From', '')
        subj = msg.get('Subject', '')
        date = msg.get('Date', '')
        
        body = ''
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype in ['text/plain', 'message/delivery-status']:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body += payload.decode('utf-8', errors='ignore') + '\n'
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode('utf-8', errors='ignore')

        is_bounce = any(k in frm.lower() for k in ['mailer-daemon', 'postmaster', 'userdoesntexist']) or \
                    any(k in subj.lower() for k in ['delivery status', 'undeliverable', 'failure', 'returned to sender', 'user does not exist']) or \
                    'address not found' in body.lower() or '550' in body

        if is_bounce:
            # Patterns to find bounced address
            m1 = re.findall(r'final-recipient:\s*rfc822;\s*([^\s;]+)', body, re.IGNORECASE)
            m2 = re.findall(r"wasn't delivered to\s+([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", body, re.IGNORECASE)
            m3 = re.findall(r"failed:\s*([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", body, re.IGNORECASE)
            m4 = re.findall(r"<([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)>:\s*5\d\d", body, re.IGNORECASE)
            candidates = set(m1 + m2 + m3 + m4)
            if not candidates:
                for c in re.findall(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', body):
                    if c.lower() != settings.imap_user.lower() and not any(d in c.lower() for d in ['google.com', 'googlemail.com', 'example.com']):
                        candidates.add(c)
                        break
            for c in candidates:
                bounced_addrs.add(c.lower().strip('<>'))
        else:
            if settings.imap_user.lower() not in frm.lower() and not any(k in frm.lower() for k in ['instagram', 'tailor brands']):
                genuine_replies.append({'from': frm, 'subject': subj, 'date': date, 'snippet': body[:200].replace('\n', ' ')})

    print(f"Total Unique Bounced Addresses detected: {len(bounced_addrs)}")

    # Deduplicate sent leads by email
    unique_sent = {}
    for s in sent_leads:
        unique_sent[s['to']] = s

    delivered = []
    bounced = []

    for email_addr, item in unique_sent.items():
        if email_addr in bounced_addrs:
            bounced.append(item)
        else:
            delivered.append(item)

    print("\n" + "="*50)
    print(f"TOTAL SENT LEADS EVALUATED: {len(unique_sent)}")
    print(f"BOUNCED (Address Not Found / 550 Mailbox Unavailable): {len(bounced)}")
    print(f"CORRECTLY DELIVERED (Accepted by Destination Server, No Bounce): {len(delivered)}")
    print("="*50)

    print("\n--- CONFIRMED DELIVERED EMAILS (NO 'ADDRESS NOT FOUND' BOUNCE) ---")
    for i, d in enumerate(delivered, 1):
        print(f"{i}. {d['to']} | {d['subject'][:55]}")

    print("\n--- BOUNCED EMAILS ('ADDRESS NOT FOUND' / 550 REJECTIONS) ---")
    for i, b in enumerate(bounced, 1):
        print(f"{i}. {b['to']}")

    print("\n--- GENUINE INBOUND REPLIES ---")
    if genuine_replies:
        for r in genuine_replies:
            print(f"From: {r['from']}\nSubject: {r['subject']}\nDate: {r['date']}\nPreview: {r['snippet']}\n{'-'*40}")
    else:
        print("No new human replies received since Sep 4.")

if __name__ == '__main__':
    main()
