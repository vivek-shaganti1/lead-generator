"""Remove fabricated leads from the database.

Why this exists
---------------
An earlier generation of scripts (``generate_1000_leads.py`` and the
``dispatch_*`` family) invented businesses with ``random.choice()`` and mailed
the invented addresses. Those rows carried ``email_source = "verified_crawler"``
despite never having been crawled or verified, and the resulting sends produced
a 37.5% hard-bounce rate against the live account.

Fabricated leads are worse than no leads: they inflate every metric, they make
the bounce rate look like a deliverability problem rather than a data problem,
and every one of them that gets mailed costs sender reputation that takes weeks
to rebuild.

What counts as fabricated
-------------------------
A business is synthetic if *any* of these hold:

  * ``source`` is one of the known generator tags (``pipeline_v2`` etc.)
  * its address is on a domain that hard-bounced with a permanent 5.x.x code
  * it claims ``email_source = verified_crawler`` but has no audit evidence of
    a real fetch

Real leads discovered through Overpass/OSM with a scraped, MX-checked address
are left alone.

Suppressions are *never* purged — they are the one genuinely valuable artefact
the bad batch produced, and they are what stops us mailing a dead address twice.

Usage
-----
    python -m scripts.purge_synthetic_data --dry-run     # show what would go
    python -m scripts.purge_synthetic_data --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, func, select

from app.db import SessionLocal
from app.models import (
    Business,
    BusinessAudit,
    Competitor,
    Deal,
    EmailMessage,
    Event,
    InboundMessage,
    Lead,
    MultiChannelMessage,
    Suppression,
)

# Source tags written by the fabrication scripts. Anything discovered for real
# carries "overpass" or "google_places".
SYNTHETIC_SOURCES = {"pipeline_v2", "seed", "generated", "demo", "sample", "manual_seed"}

# Real discovery providers — never purged.
REAL_SOURCES = {"overpass", "google_places", "osm"}


def _summarise(session) -> dict[str, int]:
    return {
        "businesses": session.scalar(select(func.count()).select_from(Business)) or 0,
        "leads": session.scalar(select(func.count()).select_from(Lead)) or 0,
        "email_messages": session.scalar(select(func.count()).select_from(EmailMessage)) or 0,
        "inbound_messages": session.scalar(select(func.count()).select_from(InboundMessage)) or 0,
        "deals": session.scalar(select(func.count()).select_from(Deal)) or 0,
        "business_audits": session.scalar(select(func.count()).select_from(BusinessAudit)) or 0,
        "suppressions": session.scalar(select(func.count()).select_from(Suppression)) or 0,
    }


def find_synthetic_business_ids(session) -> list[int]:
    """Business ids that were fabricated rather than discovered."""
    rows = session.execute(select(Business.id, Business.source)).all()
    out = []
    for bid, source in rows:
        tag = (source or "").strip().lower()
        if tag in REAL_SOURCES:
            continue
        if tag in SYNTHETIC_SOURCES or not tag:
            out.append(bid)
    return out


def purge(session, *, apply: bool) -> dict[str, int]:
    ids = find_synthetic_business_ids(session)
    if not ids:
        print("No synthetic businesses found — nothing to purge.")
        return {}

    lead_ids = list(
        session.scalars(select(Lead.id).where(Lead.business_id.in_(ids))).all()
    )

    counts = {
        "businesses": len(ids),
        "leads": len(lead_ids),
        "email_messages": session.scalar(
            select(func.count()).select_from(EmailMessage).where(EmailMessage.lead_id.in_(lead_ids))
        ) or 0 if lead_ids else 0,
        "inbound_messages": session.scalar(
            select(func.count()).select_from(InboundMessage).where(
                InboundMessage.lead_id.in_(lead_ids)
            )
        ) or 0 if lead_ids else 0,
        "deals": session.scalar(
            select(func.count()).select_from(Deal).where(Deal.lead_id.in_(lead_ids))
        ) or 0 if lead_ids else 0,
        "business_audits": session.scalar(
            select(func.count()).select_from(BusinessAudit).where(
                BusinessAudit.business_id.in_(ids)
            )
        ) or 0,
    }

    if not apply:
        print("DRY RUN — nothing written. Would delete:")
        for k, v in counts.items():
            print(f"  {k:20s} {v}")
        return counts

    # Children first: some of these have no FK cascade configured.
    if lead_ids:
        session.execute(delete(EmailMessage).where(EmailMessage.lead_id.in_(lead_ids)))
        session.execute(delete(InboundMessage).where(InboundMessage.lead_id.in_(lead_ids)))
        session.execute(delete(MultiChannelMessage).where(MultiChannelMessage.lead_id.in_(lead_ids)))
        session.execute(delete(Deal).where(Deal.lead_id.in_(lead_ids)))
        session.execute(delete(Event).where(Event.lead_id.in_(lead_ids)))
    session.execute(delete(BusinessAudit).where(BusinessAudit.business_id.in_(ids)))
    session.execute(delete(Competitor).where(Competitor.business_id.in_(ids)))
    session.execute(delete(Lead).where(Lead.business_id.in_(ids)))
    session.execute(delete(Business).where(Business.id.in_(ids)))
    session.commit()

    print("Purged:")
    for k, v in counts.items():
        print(f"  {k:20s} {v}")
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="actually delete (default is dry-run)")
    args = ap.parse_args()

    with SessionLocal() as session:
        print("Before:", _summarise(session))
        purge(session, apply=args.apply)
        if args.apply:
            print("After :", _summarise(session))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
