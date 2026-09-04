import imaplib
import email
import sys
import os
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / 'backend'))
from app.config import settings

def main():
    mail = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
    mail.login(settings.imap_user, settings.imap_password)
    print(f"Logged in as {settings.imap_user}")

    # 1. Inspect Sent Mail
    status, folders = mail.list()
    sent_folder = None
    for f in folders:
        decoded = f.decode()
        if 'Sent' in decoded:
            sent_folder = decoded.split(' "/" ')[-1].strip('"')
            break

    print(f"Sent folder: {sent_folder}")
    mail.select(f'"{sent_folder}"')
    _, data = mail.search(None, 'ALL')
    sent_ids = data[0].split()
    print(f"Total Sent Emails in account: {len(sent_ids)}")

    # Fetch last 120 sent email headers in batch
    recent_sent = []
    if sent_ids:
        batch_ids = b','.join(sent_ids[-120:])
        _, batch_data = mail.fetch(batch_ids, '(BODY.PEEK[HEADER.FIELDS (TO FROM SUBJECT DATE)])')
        for item in batch_data:
            if isinstance(item, tuple):
                msg = email.message_from_bytes(item[1])
                recent_sent.append({
                    'to': msg.get('To', ''),
                    'from': msg.get('From', ''),
                    'subject': msg.get('Subject', ''),
                    'date': msg.get('Date', '')
                })

    print(f"Successfully retrieved {len(recent_sent)} recent sent messages.")
    print("\n--- SAMPLE OF RECENT SENT EMAILS (Last 15) ---")
    for s in recent_sent[-15:]:
        print(f"To: {s['to']} | Subj: {s['subject'][:60]} | Date: {s['date']}")

    # 2. Inspect INBOX
    mail.select('INBOX')
    _, data = mail.search(None, 'ALL')
    inbox_ids = data[0].split()
    print(f"\nTotal Inbox Emails in account: {len(inbox_ids)}")

    bounces = []
    replies = []
    others = []

    if inbox_ids:
        batch_ids = b','.join(inbox_ids[-150:])
        _, batch_data = mail.fetch(batch_ids, '(BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE)])')
        headers = []
        for item in batch_data:
            if isinstance(item, tuple):
                msg = email.message_from_bytes(item[1])
                headers.append(msg)

        for msg in headers:
            frm = msg.get('From', '')
            subj = msg.get('Subject', '')
            date = msg.get('Date', '')

            is_bounce = any(k in frm.lower() for k in ['mailer-daemon', 'mail delivery', 'postmaster']) or \
                        any(k in subj.lower() for k in ['failure', 'delivery status', 'undelivered', 'returned to sender', 'address not found'])
            
            is_self = settings.imap_user.lower() in frm.lower()

            if is_bounce:
                bounces.append({'from': frm, 'subj': subj, 'date': date})
            elif not is_self:
                replies.append({'from': frm, 'subj': subj, 'date': date})
            else:
                others.append({'from': frm, 'subj': subj, 'date': date})

    print(f"\n--- BOUNCES DETECTED IN RECENT INBOX: {len(bounces)} ---")
    for b in bounces[-25:]:
        print(f"Bounce: {b['subj']} | From: {b['from']} | Date: {b['date']}")

    print(f"\n--- REPLIES / INCOMING LEADS IN INBOX: {len(replies)} ---")
    for r in replies:
        print(f"INCOMING: From: {r['from']} | Subj: {r['subj']} | Date: {r['date']}")

if __name__ == '__main__':
    main()
