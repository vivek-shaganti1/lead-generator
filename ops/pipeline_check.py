"""Drive the whole pipeline in-process, with no external network calls.

Proves the chain actually connects: candidate -> business -> qualified lead ->
approval -> dry-run send -> message + event rows -> stats rollup.
"""
from __future__ import annotations

import sys

from app.db import SessionLocal
from app.models import Business, EmailMessage, Event, Lead, LeadStatus
from app.services import stats as stats_service
from app.services.discovery.base import PlaceCandidate
from app.services.outreach import dispatcher
from app.services.pipeline import (
    get_or_create_default_campaign,
    ingest_candidates,
    qualify_business,
)

OK, BAD = [], []


def check(name, cond, detail=""):
    (OK if cond else BAD).append(name if cond else f"{name} — {detail}")


CANDIDATES = [
    PlaceCandidate(source="osm", source_id="e2e-1", name="Bella Cucina",
                   category="restaurant", phone="+353 1 555 0101",
                   email="owner@bellacucina.ie", website=None, address="1 Dame St", city="Dublin",
                   country_code="IE", lat=53.3441, lon=-6.2675),
    PlaceCandidate(source="osm", source_id="e2e-2", name="Clip & Comb",
                   category="hairdresser", phone="+353 1 555 0102",
                   email="hello@clipandcomb.ie", website="https://facebook.com/clipandcomb", city="Dublin",
                   country_code="IE", lat=53.3450, lon=-6.2600),
    PlaceCandidate(source="osm", source_id="e2e-3", name="Grafton Dental",
                   category="dentist", phone="+353 1 555 0103",
                   email="hello@graftondental.ie", website="https://graftondental.ie",
                   city="Dublin", country_code="IE", lat=53.3400, lon=-6.2590),
]

db = SessionLocal()
try:
    campaign = get_or_create_default_campaign(db)
    db.commit()

    # 1. ingest -------------------------------------------------------------
    st = ingest_candidates(db, CANDIDATES)
    db.commit()
    check("3 candidates ingested as new businesses", st.new == 3, st.as_dict())
    check("2 of them have no real website", st.without_website == 2, st.as_dict())

    # re-ingesting the same places must not duplicate
    st2 = ingest_candidates(db, CANDIDATES)
    db.commit()
    check("re-ingest is idempotent (updates, never duplicates)",
          st2.new == 0 and st2.updated == 3, st2.as_dict())
    check("business table holds exactly 3 rows",
          db.query(Business).count() == 3, db.query(Business).count())

    # 2. qualify ------------------------------------------------------------
    qualified = 0
    reasons = []
    for business in db.query(Business).all():
        result = qualify_business(db, business, campaign, check_site=False)
        reasons.append((business.name, result.created, result.reason))
        if result.created:
            qualified += 1
    db.commit()
    print("  qualify outcomes:", reasons)
    check("businesses without a working site became leads", qualified >= 2, qualified)

    leads = db.query(Lead).all()
    check("every lead carries a 0-100 score",
          all(0 <= lead.score <= 100 for lead in leads), [l.score for l in leads])
    check("the social-only listing is treated as having no website",
          any(l.business.name == "Clip & Comb" for l in leads),
          [l.business.name for l in leads])
    check("the business with a live site was not turned into a lead",
          not any(l.business.name == "Grafton Dental" for l in leads),
          [l.business.name for l in leads])

    # 3. approve + dry-run send --------------------------------------------
    if not leads:
        print("  no leads were created; stopping before the outreach stage")
        raise SystemExit(1)
    target = leads[0]
    target.email = target.email or "owner@example.com"
    dispatcher.approve_lead(db, target, True)
    db.commit()
    check("approval flips the lead out of NEEDS_APPROVAL",
          target.status != LeadStatus.NEEDS_APPROVAL, target.status)

    outcome = dispatcher.send_lead(db, target, force=True)
    db.commit()
    check("dry-run send reports success", outcome.sent, outcome)

    message = db.query(EmailMessage).filter(EmailMessage.lead_id == target.id).first()
    check("the rendered message is persisted", message is not None)
    if message:
        check("subject was rendered from the template (no raw Jinja left)",
              "{{" not in (message.subject or ""), message.subject)
        check("body was rendered from the template",
              "{{" not in (message.body_text or ""), (message.body_text or "")[:120])
        check("the business name reached the copy",
              target.business.name in (message.body_text or "") or
              target.business.name in (message.subject or ""),
              (message.subject, (message.body_text or "")[:200]))
        check("an unsubscribe link is present in every message",
              "/u/" in (message.body_text or ""), (message.body_text or "")[-300:])
        check("the postal address required by CAN-SPAM is in the footer",
              any(tok in (message.body_text or "") for tok in ("Street", "Hyderabad", "India")),
              (message.body_text or "")[-300:])

    db.refresh(target)
    check("lead advanced to CONTACTED", target.status == LeadStatus.CONTACTED, target.status)
    check("a follow-up is scheduled", target.next_action_at is not None, target.next_action_at)
    check("an audit Event row was written",
          db.query(Event).filter(Event.lead_id == target.id).count() > 0)

    # 4. stats --------------------------------------------------------------
    day = stats_service.rollup_day(db)
    db.commit()
    check("today's rollup counts the send", day.emails_sent >= 1, day.emails_sent)

    dash = stats_service.dashboard(db, days=7)
    check("dashboard totals reflect the pipeline",
          dash["totals"]["outbound"]["emails_sent"] >= 1, dash["totals"]["outbound"])
    check("the funnel is populated", any(r["count"] for r in dash["funnel"]), dash["funnel"])
    check("timeseries has one row per day", len(dash["timeseries"]) == 7, len(dash["timeseries"]))

    # 5. suppression is enforced -------------------------------------------
    from app.services.compliance.policy import is_suppressed
    from app.models import Suppression
    db.add(Suppression(kind="email", value="blocked@example.com", reason="manual"))
    db.commit()
    check("a suppressed address is recognised", is_suppressed(db, "blocked@example.com"))
    check("an unrelated address is not suppressed", not is_suppressed(db, "fine@example.com"))
finally:
    db.close()

print("\n".join(f"  PASS  {x}" for x in OK))
if BAD:
    print("\n".join(f"  FAIL  {x}" for x in BAD))
print(f"\n{len(OK)} passed, {len(BAD)} failed")
sys.exit(1 if BAD else 0)
