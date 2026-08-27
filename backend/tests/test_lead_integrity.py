"""Tests for the guards that stop us inventing leads or mailing dead addresses.

Every test here corresponds to a failure that actually happened on the live
account, or to one the first implementation walked straight into:

  * 1,000 businesses generated with ``random.choice()`` and marked
    ``email_source = verified_crawler``
  * 464 messages sent in a day, 42 of 112 unique addresses hard-bouncing (37.5%)
  * a bot-blocked fetch (HTTP 403) reported as twelve missing capabilities
  * a major retailer reported as having no e-commerce because its basket is
    rendered client-side
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import (
    AppSetting,
    Business,
    Campaign,
    EmailMessage,
    Lead,
    LeadStatus,
    MessageStatus,
)
from app.services.ai.gap_consensus import Verdict, evaluate_gap
from app.services.enrichment.capabilities import (
    Capability,
    CapabilityFinding,
    detect_capabilities,
    priority_gap,
)
from app.services.enrichment.site_fetch import FetchQuality, SiteFetch, _classify, visible_text
from app.services.inbox.reconcile import _parse_dsn
from app.services.outreach import circuit_breaker as cb
from app.utils import utcnow

# ---------------------------------------------------------------- helpers


def _fetch(quality=FetchQuality.GOOD, html="x") -> SiteFetch:
    return SiteFetch("https://x.test", quality, 200, html, ["https://x.test"], 1500,
                     final_url="https://x.test")


def _prose(text: str, times: int = 30) -> str:
    return f"<html><body>{text * times}</body></html>"


# ------------------------------------------------------- capability detection


class TestCapabilityDetection:
    def test_vendor_script_proves_presence(self):
        html = '<html><body><script src="https://assets.calendly.com/x.js"></script></body></html>'
        report = detect_capabilities(html, url="https://x.test")
        assert report.has(Capability.ONLINE_BOOKING)
        assert report.findings[Capability.ONLINE_BOOKING].confidence >= 0.9
        assert "calendly" in report.evidence_for(Capability.ONLINE_BOOKING)[0]

    def test_phrase_is_weaker_than_vendor(self):
        report = detect_capabilities(_prose("Please book now by phone. "), url="https://x.test")
        found = report.findings[Capability.ONLINE_BOOKING]
        assert found.present
        # A phrase must not carry vendor-grade certainty; it may just be "call to book".
        assert found.confidence < 0.7

    def test_missing_viewport_is_recorded_as_a_fact(self):
        report = detect_capabilities("<html><body>hello</body></html>", url="https://x.test")
        found = report.findings[Capability.MOBILE_RESPONSIVE]
        assert not found.present
        assert found.confidence >= 0.85  # absence of a tag is checkable, not inferred

    def test_contact_form_needs_a_real_field(self):
        bare = detect_capabilities("<form><input type='submit'></form>", url="https://x.test")
        assert not bare.has(Capability.CONTACT_FORM)
        real = detect_capabilities(
            "<form><input type='email' name='email'><textarea></textarea></form>",
            url="https://x.test",
        )
        assert real.has(Capability.CONTACT_FORM)

    def test_priority_gap_is_trade_specific(self):
        report = detect_capabilities(_prose("We are a business. "), url="https://x.test")
        # A restaurant is judged on bookings; a plumber on quote capture.
        assert priority_gap(report, "restaurant").capability is Capability.ONLINE_BOOKING
        assert priority_gap(report, "plumber").capability is Capability.QUOTE_REQUEST


# --------------------------------------------------------------- fetch quality


class TestFetchQuality:
    def test_bot_wall_is_not_a_featureless_site(self):
        """dominos.co.uk returned 403 and was reported as missing 12 capabilities."""
        html = "<html><body>Attention Required! Cloudflare — checking your browser</body></html>"
        assert _classify(html, 403, "https://x.test") is FetchQuality.BLOCKED

    def test_parked_domain_detected(self):
        html = _prose("This domain is for sale. Buy this domain today. ")
        assert _classify(html, 200, "https://x.test") is FetchQuality.PARKED

    def test_js_shell_is_not_judgeable(self):
        """johnlewis.com was reported as having no e-commerce; its basket is JS."""
        html = '<html><body><div id="root"></div>' + "<script>" + "x" * 90_000 + "</script></body></html>"
        assert _classify(html, 200, "https://x.test") is FetchQuality.JS_RENDERED

    def test_server_rendered_page_is_judgeable(self):
        assert _classify(_prose("Real readable content about our cafe. "), 200,
                         "https://x.test") is FetchQuality.GOOD

    @pytest.mark.parametrize(
        "quality,judgeable",
        [
            (FetchQuality.GOOD, True),
            (FetchQuality.JS_RENDERED, False),
            (FetchQuality.BLOCKED, False),
            (FetchQuality.PARKED, False),
            (FetchQuality.DEAD, False),
            (FetchQuality.THIN, False),
        ],
    )
    def test_only_good_licenses_a_claim_of_absence(self, quality, judgeable):
        assert _fetch(quality).can_judge_absence is judgeable

    def test_gap_suppressed_when_fetch_is_unjudgeable(self):
        report = detect_capabilities(_prose("Some content. "), url="https://x.test")
        assert priority_gap(report, "restaurant", can_judge_absence=True) is not None
        assert priority_gap(report, "restaurant", can_judge_absence=False) is None

    def test_visible_text_ignores_scripts(self):
        html = "<html><script>var a='buy now buy now';</script><body>Hello</body></html>"
        assert "buy now" not in visible_text(html)
        assert "Hello" in visible_text(html)


# ------------------------------------------------------------- gap consensus


class TestGapConsensus:
    """The debate must never be reached when the evidence already settles it."""

    def test_present_capability_is_rejected_without_calling_the_model(self):
        html = '<script src="https://assets.calendly.com/x.js"></script>'
        report = detect_capabilities(html, url="https://x.test")
        gap = CapabilityFinding(Capability.ONLINE_BOOKING, False, 0.6, [], "none")

        def explode(*a, **k):  # a model call here would be a bug
            raise AssertionError("LLM must not be consulted; evidence is decisive")

        result = evaluate_gap({"name": "X"}, report, _fetch(html=html), gap,
                              client=type("C", (), {"enabled": True, "chat": explode})())
        assert result.verdict is Verdict.REJECTED
        assert not result.may_pitch

    def test_unjudgeable_fetch_is_rejected_without_calling_the_model(self):
        report = detect_capabilities(_prose("hi "), url="https://x.test")
        gap = CapabilityFinding(Capability.ONLINE_BOOKING, False, 0.6, [], "none")

        def explode(*a, **k):
            raise AssertionError("LLM must not be consulted on a blocked fetch")

        result = evaluate_gap({"name": "X"}, report, _fetch(FetchQuality.BLOCKED), gap,
                              client=type("C", (), {"enabled": True, "chat": explode})())
        assert result.verdict is Verdict.REJECTED

    def test_no_llm_never_silently_confirms(self):
        """Without a key the system must not default to 'send it'."""
        report = detect_capabilities(_prose("hi "), url="https://x.test")
        gap = CapabilityFinding(Capability.ONLINE_BOOKING, False, 0.6, [], "none")
        disabled = type("C", (), {"enabled": False})()
        result = evaluate_gap({"name": "X"}, report, _fetch(), gap, client=disabled)
        assert not result.may_pitch

    def test_agents_disagreeing_blocks_the_pitch(self, monkeypatch):
        import app.services.ai.gap_consensus as gc

        replies = iter(['{"position":"REAL","reasoning":"r","confidence":0.9,"business_impact":"i"}',
                        '{"position":"REFUTED","reasoning":"r","confidence":0.9,"basis":"TRADE_IRRELEVANT"}'])
        client = type("C", (), {"enabled": True, "chat": lambda *a, **k: next(replies)})()
        report = detect_capabilities(_prose("hi "), url="https://x.test")
        gap = CapabilityFinding(Capability.ONLINE_BOOKING, False, 0.6, [], "none")
        result = gc.evaluate_gap({"name": "X"}, report, _fetch(), gap, client=client)
        assert result.verdict is Verdict.UNCERTAIN
        assert not result.may_pitch

    def test_speculative_refutation_is_discounted(self):
        """Otherwise 'it might be hidden in JS' vetoes every claim forever."""
        import app.services.ai.gap_consensus as gc

        replies = iter(['{"position":"REAL","reasoning":"r","confidence":0.9,"business_impact":"i"}',
                        '{"position":"REFUTED","reasoning":"might be JS","confidence":0.7,"basis":"SPECULATIVE"}'])
        client = type("C", (), {"enabled": True, "chat": lambda *a, **k: next(replies)})()
        report = detect_capabilities(_prose("hi "), url="https://x.test")
        gap = CapabilityFinding(Capability.ONLINE_BOOKING, False, 0.6, [], "none")
        result = gc.evaluate_gap({"name": "X"}, report, _fetch(), gap, client=client)
        assert result.verdict is Verdict.CONFIRMED


# ------------------------------------------------------------ circuit breaker


class TestCircuitBreaker:
    @staticmethod
    def _seed(db, sent: int, bounced: int, dry: bool = False) -> None:
        campaign = db.query(Campaign).first()
        if campaign is None:
            campaign = Campaign(name="cb", subject_template="s", body_template="b")
            db.add(campaign)
            db.flush()
        start = db.query(Business).count()
        for i in range(start, start + sent):
            biz = Business(source="overpass", source_id=f"cb{i}", dedupe_key=f"cb{i}",
                           name="B", has_website=False, raw={})
            db.add(biz)
            db.flush()
            lead = Lead(
                business_id=biz.id, campaign_id=campaign.id, email=f"cb{i}@x.test",
                email_source="website_scrape", email_confidence=0.9, is_role_account=False,
                status=LeadStatus.BOUNCED if i - start < bounced else LeadStatus.CONTACTED,
                score=50.0, approved=True, unsubscribe_token=f"cb{i}", followups_sent=0,
            )
            db.add(lead)
            db.flush()
            db.add(EmailMessage(
                lead_id=lead.id, to_email=lead.email, from_email="me@x.test", subject="s",
                body_text="b", body_html=None, status=MessageStatus.SENT,
                sent_at=utcnow() - timedelta(hours=1), dry_run=dry,
            ))
        db.commit()

    def test_small_sample_does_not_trip(self, db):
        """Warmup volumes are tiny; 2 bounces out of 3 proves nothing."""
        self._seed(db, sent=5, bounced=5)
        assert cb.check(db).open is False

    def test_the_real_27_august_batch_trips(self, db):
        self._seed(db, sent=112, bounced=42)
        state = cb.check(db)
        assert state.open
        assert state.bounce_rate == pytest.approx(0.375, abs=0.01)

    def test_healthy_list_does_not_trip(self, db):
        self._seed(db, sent=100, bounced=1)
        assert cb.check(db).open is False

    def test_breaker_is_sticky(self, db):
        self._seed(db, sent=112, bounced=42)
        assert cb.check(db).open
        self._seed(db, sent=200, bounced=0)   # a flood of good sends
        assert cb.check(db).open, "good sends must not silently re-close it"

    def test_reset_requires_the_data_to_be_good(self, db):
        self._seed(db, sent=112, bounced=42)
        cb.check(db)
        cb.reset(db)
        assert cb.check(db).open, "reset alone must not clear a still-bad list"

    def test_dry_run_sends_do_not_dilute_the_rate(self, db):
        self._seed(db, sent=200, bounced=0, dry=True)
        self._seed(db, sent=20, bounced=10)
        sample, bounced, rate = cb.measure(db)
        assert sample == 20, "dry-run messages never touched a server"
        assert rate == pytest.approx(0.5)


# ------------------------------------------------------------- bounce parsing


class TestDSNParsing:
    def _dsn(self, body: str) -> "object":
        import email as email_mod
        return email_mod.message_from_string(
            "From: mailer-daemon@googlemail.com\n"
            "Content-Type: multipart/report; report-type=delivery-status; boundary=B\n"
            "\n--B\nContent-Type: text/plain\n\nfailed\n"
            f"--B\nContent-Type: message/delivery-status\n\n{body}\n--B--\n"
        )

    def test_permanent_failure_is_extracted(self):
        found = _parse_dsn(self._dsn(
            "Action: failed\nFinal-Recipient: rfc822; reyesboxinggym@gmail.com\n"
            "Status: 5.1.1\nDiagnostic-Code: smtp; 550-5.1.1 does not exist\n"
        ))
        assert len(found) == 1
        assert found[0].email == "reyesboxinggym@gmail.com"
        assert found[0].permanent

    def test_transient_failure_is_not_permanent(self):
        """4.x.x is a full mailbox or greylisting — suppressing it loses a good lead."""
        found = _parse_dsn(self._dsn(
            "Action: failed\nFinal-Recipient: rfc822; busy@example.com\nStatus: 4.2.2\n"
        ))
        assert found[0].permanent is False

    def test_delayed_notices_are_ignored(self):
        assert _parse_dsn(self._dsn(
            "Action: delayed\nFinal-Recipient: rfc822; slow@example.com\nStatus: 4.4.1\n"
        )) == []
