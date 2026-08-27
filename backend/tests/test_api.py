from __future__ import annotations

from app.config import settings
from app.models import LeadStatus, Suppression
from app.utils import utcnow
from tests.conftest import make_business, make_lead


# ----------------------------------------------------------------------- auth
def test_login_succeeds(client, db):
    from app.security import ensure_admin_user

    ensure_admin_user(db)
    db.commit()
    response = client.post("/api/auth/login", json={
        "email": settings.admin_email, "password": settings.admin_password})
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"


def test_login_rejects_wrong_password(client, db):
    from app.security import ensure_admin_user

    ensure_admin_user(db)
    db.commit()
    response = client.post("/api/auth/login", json={
        "email": settings.admin_email, "password": "wrong"})
    assert response.status_code == 401
    assert "Invalid email or password" in response.json()["detail"]


def test_admin_password_follows_env_on_restart(client, db, monkeypatch):
    """Rotating ADMIN_PASSWORD in .env and restarting must actually take effect."""
    from app.security import ensure_admin_user, verify_password

    ensure_admin_user(db)
    db.commit()

    monkeypatch.setattr(settings, "admin_password", "a-freshly-rotated-password")
    user = ensure_admin_user(db)
    db.commit()

    assert verify_password("a-freshly-rotated-password", user.password_hash)
    assert client.post("/api/auth/login", json={
        "email": settings.admin_email,
        "password": "a-freshly-rotated-password"}).status_code == 200


def test_admin_seed_is_idempotent_when_password_is_unchanged(client, db):
    """A plain restart must not churn the hash or create a second admin."""
    from app.models import User
    from app.security import ensure_admin_user

    first = ensure_admin_user(db)
    db.commit()
    original_hash = first.password_hash

    ensure_admin_user(db)
    db.commit()

    assert first.password_hash == original_hash
    assert db.query(User).filter(User.email == settings.admin_email.lower()).count() == 1


def test_login_rejects_unknown_user_with_same_message(client):
    response = client.post("/api/auth/login", json={
        "email": "ghost@nowhere.ie", "password": "whatever"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


def test_login_is_rate_limited(client, db):
    """The one unauthenticated endpoint must not be brute-forceable."""
    from app.security import ensure_admin_user, limiter

    ensure_admin_user(db)
    db.commit()

    limiter.reset()
    limiter.enabled = True
    try:
        codes = [
            client.post("/api/auth/login", json={
                "email": settings.admin_email, "password": "wrong"}).status_code
            for _ in range(12)
        ]
    finally:
        limiter.enabled = False
        limiter.reset()

    assert codes[0] == 401           # the limit does not break normal use
    assert 429 in codes              # ...but a burst is refused
    assert codes.count(401) == 10    # exactly auth_rate_limit attempts got through


def test_login_rate_limit_is_disabled_under_env_test():
    """Otherwise every fixture that logs in would throttle the rest of the suite."""
    from app.security import limiter

    assert settings.env == "test"
    assert limiter.enabled is False


def test_protected_route_requires_token(client):
    assert client.get("/api/leads").status_code == 401
    assert client.get("/api/stats/dashboard").status_code == 401


def test_invalid_token_rejected(client):
    client.headers.update({"Authorization": "Bearer not-a-real-token"})
    assert client.get("/api/leads").status_code == 401


def test_me_returns_current_user(auth_client):
    response = auth_client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == settings.admin_email


# ---------------------------------------------------------------------- leads
def test_list_leads_paginates(auth_client, db, campaign):
    for i in range(3):
        make_lead(db, business=make_business(db, source_id=f"n{i}"), campaign=campaign,
                  email=f"a{i}@shop.ie", score=float(i))
    response = auth_client.get("/api/leads", params={"page_size": 2})
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["items"][0]["score"] >= body["items"][1]["score"]


def test_list_leads_filters(auth_client, db, campaign):
    make_lead(db, business=make_business(db, source_id="ie", country_code="IE"),
              campaign=campaign, email="a@shop.ie", status=LeadStatus.READY)
    make_lead(db, business=make_business(db, source_id="in", country_code="IN",
                                         phone="+91 98765 43210"),
              campaign=campaign, email="b@shop.in", status=LeadStatus.CONTACTED)

    assert auth_client.get("/api/leads", params={"country": "IE"}).json()["total"] == 1
    assert auth_client.get("/api/leads", params={"status": "CONTACTED"}).json()["total"] == 1
    assert auth_client.get("/api/leads", params={"search": "shop.in"}).json()["total"] == 1
    assert auth_client.get("/api/leads", params={"min_score": 99}).json()["total"] == 0


def test_get_lead_detail_and_404(auth_client, db, campaign):
    lead = make_lead(db, campaign=campaign)
    body = auth_client.get(f"/api/leads/{lead.id}").json()
    assert body["business"]["name"] == "Rossi's Trattoria"
    assert body["messages"] == []
    assert auth_client.get("/api/leads/99999").status_code == 404


def test_patch_lead_approves(auth_client, db, campaign):
    lead = make_lead(db, campaign=campaign, approved=False,
                     status=LeadStatus.NEEDS_APPROVAL)
    body = auth_client.patch(f"/api/leads/{lead.id}", json={"approved": True}).json()
    assert body["approved"] is True
    assert body["status"] == "READY"


def test_patch_lead_notes_and_contact_name(auth_client, db, campaign):
    lead = make_lead(db, campaign=campaign)
    body = auth_client.patch(
        f"/api/leads/{lead.id}", json={"contact_name": "Maria", "notes": "called them"}
    ).json()
    assert body["contact_name"] == "Maria"
    assert body["notes"] == "called them"


def test_send_now_endpoint(auth_client, db, campaign, transport):
    lead = make_lead(db, campaign=campaign)
    response = auth_client.post(f"/api/leads/{lead.id}/send")
    assert response.status_code == 200
    assert response.json()["sent"] is True
    assert len(transport.sent) == 1


def test_send_now_conflict_when_blocked(auth_client, db, campaign, transport):
    lead = make_lead(db, campaign=campaign, approved=False,
                     status=LeadStatus.NEEDS_APPROVAL)
    response = auth_client.post(f"/api/leads/{lead.id}/send")
    assert response.status_code == 409
    assert "approval" in response.json()["detail"]
    assert transport.sent == []


def test_bulk_approve(auth_client, db, campaign):
    ids = [
        make_lead(db, business=make_business(db, source_id=f"n{i}"), campaign=campaign,
                  email=f"a{i}@shop.ie", approved=False,
                  status=LeadStatus.NEEDS_APPROVAL).id
        for i in range(3)
    ]
    response = auth_client.post("/api/leads/bulk",
                                json={"lead_ids": ids, "action": "approve"})
    assert response.json()["affected"] == 3
    assert auth_client.get("/api/leads",
                           params={"status": "READY"}).json()["total"] == 3


def test_bulk_suppress(auth_client, db, campaign):
    lead = make_lead(db, campaign=campaign)
    auth_client.post("/api/leads/bulk", json={"lead_ids": [lead.id], "action": "suppress"})
    assert db.query(Suppression).count() == 1
    assert auth_client.get(f"/api/leads/{lead.id}").json()["status"] == "DO_NOT_CONTACT"


def test_bulk_rejects_unknown_action(auth_client, db, campaign):
    lead = make_lead(db, campaign=campaign)
    response = auth_client.post("/api/leads/bulk",
                                json={"lead_ids": [lead.id], "action": "nuke"})
    assert response.status_code == 422


# ------------------------------------------------------------------ campaigns
def test_campaign_crud(auth_client):
    created = auth_client.post("/api/campaigns", json={
        "name": "Cafes IE",
        "subject_template": "Hi {{ business_name }}",
        "body_template": "Body for {{ city }} {{ unsubscribe_url }}",
    })
    assert created.status_code == 201
    campaign_id = created.json()["id"]

    duplicate = auth_client.post("/api/campaigns", json={
        "name": "Cafes IE", "subject_template": "x", "body_template": "y"})
    assert duplicate.status_code == 409

    updated = auth_client.put(f"/api/campaigns/{campaign_id}", json={
        "name": "Cafes IE", "subject_template": "Hello {{ business_name }}",
        "body_template": "Updated {{ city }}"})
    assert updated.json()["subject_template"] == "Hello {{ business_name }}"


def test_campaign_rejects_broken_template(auth_client):
    response = auth_client.post("/api/campaigns", json={
        "name": "Broken", "subject_template": "Hi {{ business_name }}",
        "body_template": "{{ not_a_real_variable }}"})
    assert response.status_code == 422
    assert "body_template" in response.json()["detail"]


def test_campaign_preview_without_lead(auth_client):
    body = auth_client.post("/api/campaigns/preview", json={"step": 0}).json()
    assert "Rossi's Trattoria" in body["subject"]
    assert "Unsubscribe" in body["text"]


def test_campaign_preview_for_lead(auth_client, db, campaign):
    lead = make_lead(db, campaign=campaign)
    body = auth_client.post("/api/campaigns/preview",
                            json={"lead_id": lead.id, "step": 1}).json()
    assert body["subject"].startswith("Re:")


# ------------------------------------------------------------------ discovery
def test_categories_endpoint(auth_client):
    body = auth_client.get("/api/discovery/categories").json()
    assert any(item["key"] == "restaurant" for item in body)


def test_discovery_validates_scope(auth_client):
    response = auth_client.post("/api/discovery/run",
                                json={"label": "Nowhere", "run_async": False})
    assert response.status_code == 422
    assert "bbox or area_name" in response.json()["detail"]


def test_discovery_rejects_inverted_bbox(auth_client):
    response = auth_client.post("/api/discovery/run", json={
        "label": "Bad", "run_async": False,
        "bbox": {"south": 52.0, "west": -8.0, "north": 51.0, "east": -7.0}})
    assert response.status_code == 422


def test_discovery_rejects_unknown_category(auth_client):
    response = auth_client.post("/api/discovery/run", json={
        "label": "Cork", "run_async": False, "categories": ["spaceport"],
        "bbox": {"south": 51.8, "west": -8.6, "north": 51.9, "east": -8.4}})
    assert response.status_code == 422


def test_discovery_runs_listed(auth_client):
    assert auth_client.get("/api/discovery/runs").json() == []
    assert auth_client.get("/api/discovery/runs/1").status_code == 404


# --------------------------------------------------------------------- stats
def test_dashboard_endpoint(auth_client):
    body = auth_client.get("/api/stats/dashboard", params={"days": 7}).json()
    assert "totals" in body and "funnel" in body
    assert len(body["timeseries"]) == 7


def test_rollup_endpoint(auth_client):
    assert auth_client.post("/api/stats/rollup", params={"days": 3}).json()["days_rolled"] == 3


def test_events_endpoint(auth_client, db, campaign, transport):
    from app.services.outreach.dispatcher import send_lead

    lead = make_lead(db, campaign=campaign)
    send_lead(db, lead)
    db.commit()
    events = auth_client.get("/api/stats/events").json()
    assert any(event["type"] == "outreach.sent" for event in events)


# -------------------------------------------------------------------- system
def test_health_is_public(client):
    body = client.get("/api/system/health").json()
    assert body["status"] == "ok"
    assert body["database"] is True
    assert body["dry_run"] is True


def test_config_endpoint_hides_secrets(auth_client):
    body = auth_client.get("/api/system/config").json()
    flat = str(body)
    assert settings.admin_password not in flat
    assert settings.secret_key not in flat
    assert body["dry_run"] is True
    assert "DE" in body["blocked_countries"]


def test_suppression_crud(auth_client):
    created = auth_client.post("/api/system/suppressions",
                               json={"value": "spammy@shop.ie", "reason": "complained"})
    assert created.status_code == 201
    suppression_id = created.json()["id"]
    assert any(row["value"] == "spammy@shop.ie"
               for row in auth_client.get("/api/system/suppressions").json())
    assert auth_client.delete(f"/api/system/suppressions/{suppression_id}").status_code == 204
    assert auth_client.delete(f"/api/system/suppressions/{suppression_id}").status_code == 404


def test_test_email_endpoint_uses_dry_run(auth_client, transport):
    body = auth_client.post("/api/system/test/email",
                            json={"to_email": "me@shop.ie"}).json()
    assert body["dry_run"] is True
    assert len(transport.sent) == 1


def test_telegram_test_requires_config(auth_client):
    assert auth_client.post("/api/system/test/telegram").status_code == 400


def test_groq_test_requires_config(auth_client):
    assert auth_client.post("/api/system/test/groq").status_code == 400


def test_sending_snapshot(auth_client):
    body = auth_client.get("/api/system/sending").json()
    assert body["remaining"] >= 0


# -------------------------------------------------------------------- public
def test_unsubscribe_page_and_submit(client, db, campaign):
    lead = make_lead(db, campaign=campaign)
    token = lead.unsubscribe_token

    page = client.get(f"/u/{token}")
    assert page.status_code == 200
    assert lead.email in page.text

    submitted = client.post(f"/u/{token}")
    assert submitted.status_code == 200
    assert "Done" in submitted.text

    db.expire_all()
    refreshed = db.get(type(lead), lead.id)
    assert refreshed.status == LeadStatus.UNSUBSCRIBED
    assert db.query(Suppression).filter_by(value=lead.email).count() == 1


def test_unsubscribe_page_escapes_untrusted_values(client, db, campaign):
    """Lead addresses come from scraped pages; they must never render as markup."""
    lead = make_lead(db, campaign=campaign, email="a<b>c@rossis.ie")
    page = client.get(f"/u/{lead.unsubscribe_token}")
    assert page.status_code == 200
    assert "a<b>c@rossis.ie" not in page.text
    assert "a&lt;b&gt;c@rossis.ie" in page.text


def test_unsubscribe_one_click(client, db, campaign):
    lead = make_lead(db, campaign=campaign)
    response = client.post(f"/u/{lead.unsubscribe_token}",
                           content="List-Unsubscribe=One-Click",
                           headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert response.status_code == 200
    db.expire_all()
    assert db.get(type(lead), lead.id).status == LeadStatus.UNSUBSCRIBED


def test_unsubscribe_is_idempotent(client, db, campaign):
    lead = make_lead(db, campaign=campaign)
    client.post(f"/u/{lead.unsubscribe_token}")
    second = client.post(f"/u/{lead.unsubscribe_token}")
    assert second.status_code == 200
    assert db.query(Suppression).count() == 1


def test_unknown_unsubscribe_token_404(client):
    assert client.get("/u/nope").status_code == 404
    assert client.post("/u/nope").status_code == 404


def test_open_tracking_pixel(client, db, campaign):
    from app.models import EmailMessage, MessageStatus
    from app.services.outreach.tracking import make_token

    lead = make_lead(db, campaign=campaign)
    message = EmailMessage(
        lead_id=lead.id, step=0, to_email=lead.email, from_email=settings.sender_email,
        subject="s", body_text="b", status=MessageStatus.SENT, sent_at=utcnow(),
        message_id="<open@x>",
    )
    db.add(message)
    db.commit()

    response = client.get(f"/t/o/{make_token(message.id)}.gif")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/gif"

    db.expire_all()
    refreshed = db.get(EmailMessage, message.id)
    assert refreshed.open_count == 1
    assert refreshed.opened_at is not None


def test_tracking_pixel_ignores_forged_token(client):
    response = client.get("/t/o/1.forged.gif")
    assert response.status_code == 200      # still returns an image, records nothing


def test_security_headers_present(client):
    response = client.get("/")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
