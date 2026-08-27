"""Discover real businesses and qualify them into leads — evidence at every step.

This replaces the deleted ``generate_1000_leads.py`` and the ``dispatch_*``
family, which invented businesses with ``random.choice()`` and mailed the
invented addresses.

The rule that governs this file: **a lead may only exist if a real business
published a real address that we actually fetched.** Nothing is inferred,
pattern-generated, or assumed. If we cannot find a published address, the
business is recorded and skipped — not guessed at.

The funnel
----------
    1. discover     OpenStreetMap via Overpass — real places, real coordinates
    2. fetch        the site, graded for whether it can be judged at all
    3. capabilities what the site can actually do, from bytes we fetched
    4. gap          the most commercially relevant thing it lacks
    5. debate       two adversarial agents must agree the gap is real
    6. email        scraped from the business's own pages, never constructed
    7. validate     syntax, role, disposable, MX
    8. lead         created only if every step above produced evidence

Each stage prints how many candidates it dropped and why, because the drop
rates are the honest measure of this system. A run that reports 400 discovered
and 12 qualified is working correctly; one that qualifies 400 of 400 is lying.

Usage
-----
    python scripts/run_real_pipeline.py --bbox -33.92,151.24,-33.87,151.29 \
        --country AU --label "Sydney East" --categories salon,cafe,dentist --limit 60
"""
from __future__ import annotations

import argparse
import logging
import sys
import warnings
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

warnings.filterwarnings("ignore")
for _noisy in ("httpx", "httpcore", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.CRITICAL)

from sqlalchemy import select

import secrets

from app.db import SessionLocal, init_db
from app.models import Business, Campaign, Lead, LeadStatus, Suppression
from app.services.ai.gap_consensus import Verdict, evaluate_gap
from app.services.ai.groq import GroqClient
from app.services.discovery.base import SearchArea
from app.services.discovery.overpass import OverpassProvider
from app.services.enrichment.capabilities import detect_capabilities, priority_gap
from app.services.enrichment.email_finder import find_email
from app.services.enrichment.scoring import score_lead
from app.services.enrichment.site_fetch import FetchQuality, fetch_site
from app.services.enrichment.website_check import WebPresence
from app.services.enrichment.validator import validate
from app.utils import utcnow


class Funnel(Counter):
    """Stage counters, printed at the end so drop rates are always visible."""

    def show(self) -> None:
        print("\n" + "=" * 66)
        print("FUNNEL".ljust(46) + "count")
        print("=" * 66)
        for stage in (
            "discovered",
            "already_known",
            "suppressed",
            "no_website_at_all",
            "site_dead",
            "site_blocked",
            "site_parked",
            "site_js_only",
            "site_judgeable",
            "no_email_published",
            "email_invalid",
            "gap_none_found",
            "gap_rejected",
            "gap_uncertain",
            "gap_confirmed",
            "leads_created",
        ):
            if stage in self:
                print(f"  {stage.replace('_', ' '):44s}{self[stage]:>6d}")
        print("=" * 66)


def _suppressed(db, email: str) -> bool:
    domain = email.rpartition("@")[2]
    hit = db.scalar(
        select(Suppression).where(
            Suppression.value.in_([email.lower(), domain.lower()])
        )
    )
    return hit is not None


def run(args: argparse.Namespace) -> int:
    init_db()
    south, west, north, east = (float(x) for x in args.bbox.split(","))
    area = SearchArea(
        label=args.label, south=south, west=west, north=north, east=east,
        country_code=args.country,
    )
    area.validate()
    categories = [c.strip() for c in args.categories.split(",") if c.strip()]

    funnel = Funnel()
    groq = GroqClient()
    qualified: list[dict] = []

    print(f"Discovering {categories} in {args.label} ({args.country}) …")
    candidates = OverpassProvider().search(area, categories, limit=args.limit)
    funnel["discovered"] = len(candidates)
    print(f"  {len(candidates)} real businesses from OpenStreetMap\n")

    with SessionLocal() as db:
        campaign = db.scalar(select(Campaign).where(Campaign.is_active.is_(True)))
        if campaign is None:
            print("No active campaign — create one first.", file=sys.stderr)
            return 2

        for index, cand in enumerate(candidates, 1):
            label = cand.name[:38]
            print(f"[{index:3d}/{len(candidates)}] {label:40s}", end=" ", flush=True)

            if db.scalar(select(Business).where(Business.dedupe_key == cand.key)):
                funnel["already_known"] += 1
                print("· already known")
                continue

            # ---- 1. is there a site we can judge? --------------------------
            if not cand.has_real_website:
                # No website is the warmest signal there is, but with no site
                # there is usually nothing to scrape an address from either.
                funnel["no_website_at_all"] += 1
                print("· no website (no page to find an address on)")
                continue

            fetched = fetch_site(cand.website)
            if fetched.quality is FetchQuality.DEAD:
                funnel["site_dead"] += 1
                print(f"· site dead ({fetched.error[:28]})")
                continue
            if fetched.quality is FetchQuality.BLOCKED:
                funnel["site_blocked"] += 1
                print("· bot-blocked, cannot judge")
                continue
            if fetched.quality is FetchQuality.PARKED:
                funnel["site_parked"] += 1
                print("· parked/holding page")
                continue
            if fetched.quality is FetchQuality.JS_RENDERED:
                funnel["site_js_only"] += 1
                print("· JS-only shell, cannot judge absence")
                continue
            funnel["site_judgeable"] += 1

            # ---- 2. a published address, or nothing ------------------------
            finding = find_email(
                map_email=cand.email,
                website=cand.website,
                business_name=cand.name,
                country_code=cand.country_code,
            )
            if not finding:
                funnel["no_email_published"] += 1
                print("· no published address")
                continue

            checked = validate(finding.email)
            if not checked.valid:
                funnel["email_invalid"] += 1
                print(f"· address rejected ({checked.reason})")
                continue
            if _suppressed(db, checked.email):
                funnel["suppressed"] += 1
                print("· suppressed")
                continue

            # ---- 3. what is genuinely missing ------------------------------
            report = detect_capabilities(
                fetched.html, url=fetched.final_url, pages=fetched.pages
            )
            gap = priority_gap(
                report, cand.category, can_judge_absence=fetched.can_judge_absence
            )
            if gap is None:
                funnel["gap_none_found"] += 1
                print("· nothing worth pitching")
                continue

            # ---- 4. both agents must agree ---------------------------------
            consensus = evaluate_gap(
                {
                    "name": cand.name,
                    "category": cand.category,
                    "country_code": cand.country_code,
                },
                report, fetched, gap, client=groq,
            )
            if consensus.verdict is Verdict.REJECTED:
                funnel["gap_rejected"] += 1
                print(f"· gap refuted ({consensus.rationale[:26]})")
                continue
            if consensus.verdict is not Verdict.CONFIRMED:
                funnel["gap_uncertain"] += 1
                print(f"· {consensus.verdict.value.lower()}, not pitched")
                continue
            funnel["gap_confirmed"] += 1

            # ---- 5. persist, with the evidence attached --------------------
            business = Business(
                source=cand.source, source_id=cand.source_id, dedupe_key=cand.key,
                name=cand.name, category=cand.category, phone=cand.phone,
                email=checked.email, website=cand.website, has_website=True,
                website_alive=True, website_checked_at=utcnow(),
                address=cand.address, city=cand.city, region=cand.region,
                postcode=cand.postcode, country_code=cand.country_code,
                lat=cand.lat, lon=cand.lon, raw=cand.raw,
                data_provenance={
                    "discovery": cand.source,
                    "email_source": finding.source,
                    "pages_fetched": fetched.pages,
                    "fetch_quality": fetched.quality.value,
                    "capabilities": report.as_dict(),
                    "gap_consensus": consensus.as_dict(),
                    "verified_at": utcnow().isoformat(),
                },
            )
            db.add(business)
            db.flush()

            score, _breakdown = score_lead(
                presence=WebPresence.LIVE,
                category=cand.category,
                email_confidence=checked.confidence,
                is_role_account=checked.is_role,
                has_phone=bool(cand.phone),
                has_address=bool(cand.address),
                has_social=bool(cand.facebook or cand.instagram),
            )
            lead = Lead(
                business_id=business.id, campaign_id=campaign.id,
                email=checked.email, email_source=finding.source,
                email_confidence=checked.confidence, is_role_account=checked.is_role,
                status=LeadStatus.NEEDS_APPROVAL,
                score=float(score),
                approved=False,
                unsubscribe_token=secrets.token_urlsafe(24),
                followups_sent=0,
                notes=f"Confirmed gap: {consensus.capability.value}. {consensus.rationale[:300]}",
            )
            db.add(lead)
            db.commit()

            funnel["leads_created"] += 1
            qualified.append(
                {
                    "name": cand.name, "email": checked.email,
                    "city": cand.city, "country": cand.country_code,
                    "category": cand.category, "gap": consensus.capability.value,
                    "confidence": consensus.confidence, "website": cand.website,
                }
            )
            print(f"✓ LEAD  {checked.email}  gap={consensus.capability.value}")

    funnel.show()
    if qualified:
        print(f"\n{len(qualified)} QUALIFIED LEADS")
        print("-" * 66)
        for q in qualified:
            print(f"  {q['name'][:30]:30s} {q['email'][:32]:32s} {q['gap']}")
    else:
        print("\nNo leads qualified from this batch.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bbox", required=True, help="south,west,north,east")
    ap.add_argument("--country", required=True, help="ISO-2 country code")
    ap.add_argument("--label", default="area")
    ap.add_argument("--categories", default="salon,cafe,dentist,restaurant,plumber")
    ap.add_argument("--limit", type=int, default=40)
    return run(ap.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
