"""End-to-end smoke test against a live API process. Exercises the real HTTP surface."""
from __future__ import annotations
import json, os, sys, urllib.error, urllib.request

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:8010")
EMAIL = os.environ["SMOKE_EMAIL"]
PASSWORD = os.environ["SMOKE_PASSWORD"]

PASS, FAIL = [], []
TOKEN = None


def call(method, path, body=None, auth=True, expect=200, raw=False):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if auth and TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status, payload = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, payload = e.code, e.read()
    ok = status == expect
    label = f"{method} {path} -> {status}"
    (PASS if ok else FAIL).append(label if ok else f"{label} (expected {expect}) {payload[:300]!r}")
    if raw:
        return status, payload
    try:
        return status, json.loads(payload) if payload else None
    except Exception:
        return status, payload


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name if condition else f"{name}: {detail}")


# --- auth ---------------------------------------------------------------
_, tok = call("POST", "/api/auth/login", {"email": EMAIL, "password": PASSWORD}, auth=False)
TOKEN = (tok or {}).get("access_token")
check("login returns a bearer token", bool(TOKEN))
call("POST", "/api/auth/login", {"email": EMAIL, "password": "wrong"}, auth=False, expect=401)
call("GET", "/api/auth/me")
_, unauth = call("GET", "/api/leads", auth=False, expect=401)

# --- system -------------------------------------------------------------
_, health = call("GET", "/api/system/health")
check("health reports a status", isinstance(health, dict) and "status" in health, str(health)[:200])
_, cfg = call("GET", "/api/system/config")
check("config exposes dry_run", isinstance(cfg, dict) and "dry_run" in cfg, str(cfg)[:200])
check("config never leaks secrets",
      not any(k in json.dumps(cfg or {}).lower() for k in ("smtp_password", "secret_key", "groq_api_key", "api_key")),
      str(cfg)[:400])
call("GET", "/api/system/sending")

# --- suppressions round-trip -------------------------------------------
_, sup = call("POST", "/api/system/suppressions",
              {"kind": "email", "value": "smoke-test@example.com", "reason": "manual"}, expect=201)
sup_id = (sup or {}).get("id")
_, sups = call("GET", "/api/system/suppressions")
check("new suppression appears in the list",
      any(s.get("value") == "smoke-test@example.com" for s in (sups or [])), str(sups)[:200])
if sup_id:
    call("DELETE", f"/api/system/suppressions/{sup_id}", expect=204)

# --- discovery ----------------------------------------------------------
_, cats = call("GET", "/api/discovery/categories")
check("discovery exposes categories", bool(cats), str(cats)[:200])
call("GET", "/api/discovery/runs")

# --- campaigns ----------------------------------------------------------
_, camps = call("GET", "/api/campaigns")
check("a default campaign is seeded at boot", bool(camps), str(camps)[:200])

# --- leads & stats ------------------------------------------------------
_, leads = call("GET", "/api/leads?page=1&page_size=5")
check("leads endpoint is paginated",
      isinstance(leads, dict) and {"items", "total"} <= set(leads), str(leads)[:200])
call("GET", "/api/leads?status=NEW&page=1&page_size=5")
call("GET", "/api/leads?status=not_a_status&page=1&page_size=5", expect=422)
# Re-suppressing must be idempotent: the same row comes back, never a duplicate.
_, first = call("POST", "/api/system/suppressions",
                {"kind": "email", "value": "dupe@example.com", "reason": "manual"}, expect=201)
_, again = call("POST", "/api/system/suppressions",
                {"kind": "email", "value": "dupe@example.com", "reason": "manual"}, expect=201)
check("suppressing the same address twice is idempotent",
      (first or {}).get("id") == (again or {}).get("id"), f"{first} vs {again}")
_, after = call("GET", "/api/system/suppressions")
check("no duplicate suppression row is created",
      sum(1 for r in (after or []) if r.get("value") == "dupe@example.com") == 1, str(after)[:200])
call("GET", "/api/leads/999999", expect=404)
call("GET", "/api/stats/dashboard")
call("GET", "/api/stats/timeseries?days=7")
call("GET", "/api/stats/today")
call("GET", "/api/stats/events")

# --- public (unauthenticated) surface -----------------------------------
st, body = call("GET", "/u/not-a-real-token", auth=False, expect=404, raw=True)
st, pixel = call("GET", "/t/o/not-a-real-token.gif", auth=False, expect=200, raw=True)
check("tracking pixel always returns a GIF regardless of token validity",
      pixel[:3] == b"GIF", repr(pixel[:16]))

print("\n".join(f"  PASS  {p}" for p in PASS))
if FAIL:
    print("\n".join(f"  FAIL  {f}" for f in FAIL))
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
