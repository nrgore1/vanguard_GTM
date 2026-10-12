"""Measured results from the Growth Command Center (growth.jodibana.com).

Vanguard plans and runs the B2B partner pipeline; Growth runs the opted-in audiences and measures
what happens. For each property that is also a Growth brand (same id as the brand slug: weddingos,
jodiusa, jodibana, liqmint) the dashboard shows Growth's daily counts: confirmed sign-ups, referral
conversions, emails sent, hard bounces, complaints and unsubscribes.

No redundancy: the counts are read on demand and cached in memory for a few minutes. Nothing from
the feed is written to Vanguard's database, so Growth stays the only source and there is nothing
to drift or double-count. No personal data crosses: the feed carries counts and public brand facts
only, and anything else in a response is dropped here.

Off until VANGUARD_GROWTH_FEED_URL and VANGUARD_GROWTH_FEED_TOKEN are set.
  VANGUARD_GROWTH_FEED_URL        e.g. https://growth.jodibana.com/api/v1/feeds/results
  VANGUARD_GROWTH_FEED_TOKEN      the value of GROWTH_RESULTS_FEED_TOKEN on the Growth server
  VANGUARD_GROWTH_FEED_DAYS       window in days, 1-90 (default 30)
  VANGUARD_GROWTH_FEED_CACHE_SEC  how long a response is reused (default 300)
"""
from __future__ import annotations

import logging
import os
import time
from urllib.parse import urlsplit

import httpx

log = logging.getLogger("vanguard.growth_feed")
TRANSPORT: httpx.BaseTransport | None = None   # test hook: tests set an httpx.MockTransport here

COUNTS = ("confirmed_signups", "referral_conversions", "emails_sent", "hard_bounces", "complaints", "unsubscribes")
RATES = ("hard_bounce_rate", "complaint_rate")
_cache: dict[str, tuple[float, dict]] = {}


def reset_cache() -> None:
    _cache.clear()


def config() -> dict:
    url = os.getenv("VANGUARD_GROWTH_FEED_URL", "").strip()
    token = os.getenv("VANGUARD_GROWTH_FEED_TOKEN", "").strip()
    try:
        days = min(90, max(1, int(os.getenv("VANGUARD_GROWTH_FEED_DAYS", "30"))))
    except ValueError:
        days = 30
    try:
        ttl = max(0, int(os.getenv("VANGUARD_GROWTH_FEED_CACHE_SEC", "300")))
    except ValueError:
        ttl = 300
    return {"url": url, "token": token, "days": days, "ttl": ttl}


def url_problem(url: str) -> str | None:
    """The token travels in a header, so the feed must be https, except to a host on the private Docker
    network (a name without dots, such as growth-production-console) or localhost."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme == "https" and host:
        return None
    if parts.scheme == "http" and host and ("." not in host or host in ("localhost", "127.0.0.1")):
        return None
    return "VANGUARD_GROWTH_FEED_URL must be https (or http to a private Docker host name)"


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _rate(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _clean(body: object) -> dict[str, dict]:
    """Keep only the documented, non-personal fields, keyed by brand slug."""
    brands = body.get("brands") if isinstance(body, dict) else None
    out: dict[str, dict] = {}
    for b in brands if isinstance(brands, list) else []:
        if not isinstance(b, dict) or not isinstance(b.get("slug"), str):
            continue
        totals = b.get("totals") if isinstance(b.get("totals"), dict) else {}
        daily = [d for d in b.get("daily") or [] if isinstance(d, dict)]
        out[b["slug"]] = {
            "name": str(b.get("name") or b["slug"]),
            "privacy_tier": str(b.get("privacy_tier") or ""),
            "site_url": b.get("site_url") if isinstance(b.get("site_url"), str) else None,
            "markets": [m for m in b.get("markets") or [] if isinstance(m, str)],
            "totals": {k: _int(totals.get(k)) for k in COUNTS} | {k: _rate(totals.get(k)) for k in RATES},
            "daily": [{"date": str(d.get("date") or "")[:10]} | {k: _int(d.get(k)) for k in COUNTS} for d in daily],
        }
    return out


def fetch() -> dict:
    """{"configured", "ok", "error", "days", "generated_at", "brands": {slug: {...}}}. Never raises."""
    cfg = config()
    status = {"configured": bool(cfg["url"] and cfg["token"]), "ok": False, "error": None, "days": cfg["days"],
              "generated_at": None, "brands": {}}
    if not status["configured"]:
        return status
    if problem := url_problem(cfg["url"]):
        return status | {"error": problem}
    key = f"{cfg['url']}|{cfg['days']}"
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < cfg["ttl"]:
        return hit[1]
    try:
        with httpx.Client(timeout=10, transport=TRANSPORT, follow_redirects=False) as http:
            r = http.get(cfg["url"], params={"days": cfg["days"]},
                         headers={"Authorization": f"Bearer {cfg['token']}", "Accept": "application/json"})
        if r.status_code != 200:
            reason = {401: "token refused", 404: "feed not enabled on the Growth server"}.get(r.status_code, "")
            return status | {"error": f"Growth feed answered {r.status_code} {reason}".strip()}
        body = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("growth feed unavailable: %s", type(exc).__name__)
        return status | {"error": f"Growth feed unavailable ({type(exc).__name__})"}
    result = status | {"ok": True, "generated_at": body.get("generated_at") if isinstance(body, dict) else None,
                       "brands": _clean(body)}
    _cache[key] = (time.monotonic(), result)
    return result


def _host(url: str | None) -> str:
    return (urlsplit(url or "").hostname or "").lower().removeprefix("www.")


def drift(property_url: str, brand: dict) -> list[str]:
    """Growth holds the approved brand facts; flag the registry when its domain disagrees."""
    if brand.get("site_url") and _host(property_url) != _host(brand["site_url"]):
        return [f"registry url {property_url} differs from Growth site {brand['site_url']}"]
    return []
