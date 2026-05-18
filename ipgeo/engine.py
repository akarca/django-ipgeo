"""
IP geolocation engine.

Priority order:
  1. Local MaxMind GeoLite2 DB (if LOCAL_DB_PATH is configured) — no network call.
  2. Remote APIs queried sequentially; returns on first success.
"""

import ipaddress
import json
import logging
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
]


def get_client_ip(request):
    """Extract real client IP, handling reverse proxy headers."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    xri = request.META.get("HTTP_X_REAL_IP")
    if xri:
        return xri.strip()
    return request.META.get("REMOTE_ADDR", "")


def is_private_ip(ip_str):
    """Check if IP is private/localhost."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return any(ip in net for net in PRIVATE_NETWORKS)
    except ValueError:
        return True


# ---------------------------------------------------------------------------
# Service adapters — each returns {city, country, country_code, lat, lon}
# ---------------------------------------------------------------------------

def _fetch_json(url, timeout=2, user_agent="django-ipgeo/1.0"):
    """Fetch JSON with timeout. Returns dict or None."""
    try:
        req = Request(url, headers={"User-Agent": user_agent})
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def _query_ip_api(ip, timeout, user_agent):
    """ip-api.com — 45 req/min, free, no key."""
    data = _fetch_json(
        f"http://ip-api.com/json/{ip}?fields=city,country,countryCode,lat,lon,status",
        timeout, user_agent,
    )
    if data and data.get("status") == "success" and data.get("city"):
        return {
            "city": data["city"],
            "country": data["country"],
            "country_code": data["countryCode"],
            "lat": data["lat"],
            "lon": data["lon"],
        }
    return None


def _query_ipwho_is(ip, timeout, user_agent):
    """ipwho.is — unlimited, free, no key."""
    data = _fetch_json(f"https://ipwho.is/{ip}", timeout, user_agent)
    if data and data.get("success") and data.get("city"):
        return {
            "city": data["city"],
            "country": data["country"],
            "country_code": data["country_code"],
            "lat": data["latitude"],
            "lon": data["longitude"],
        }
    return None


def _query_ipapi_co(ip, timeout, user_agent):
    """ipapi.co — 30K/month free, no key."""
    data = _fetch_json(f"https://ipapi.co/{ip}/json/", timeout, user_agent)
    if data and not data.get("error") and data.get("city"):
        return {
            "city": data["city"],
            "country": data["country_name"],
            "country_code": data["country_code"],
            "lat": data["latitude"],
            "lon": data["longitude"],
        }
    return None


def _query_freeipapi(ip, timeout, user_agent):
    """freeipapi.com — free, no key."""
    data = _fetch_json(
        f"https://freeipapi.com/api/json/{ip}", timeout, user_agent,
    )
    if data and data.get("cityName"):
        return {
            "city": data["cityName"],
            "country": data["countryName"],
            "country_code": data["countryCode"],
            "lat": data["latitude"],
            "lon": data["longitude"],
        }
    return None


def _query_ip2location(ip, timeout, user_agent):
    """ip2location.io — 30K/day free, no key for basic."""
    data = _fetch_json(
        f"https://api.ip2location.io/?ip={ip}", timeout, user_agent,
    )
    if data and data.get("city_name") and data["city_name"] != "-":
        return {
            "city": data["city_name"],
            "country": data["country_name"],
            "country_code": data["country_code"],
            "lat": data.get("latitude"),
            "lon": data.get("longitude"),
        }
    return None


GEO_SERVICES = [
    _query_ip_api,
    _query_ipwho_is,
    _query_ipapi_co,
    _query_freeipapi,
    _query_ip2location,
]


# ---------------------------------------------------------------------------
# Local DB adapter (MaxMind GeoLite2-City via geoip2 library)
# ---------------------------------------------------------------------------

def _query_local_db(ip):
    """
    Query a local MaxMind GeoLite2-City .mmdb file.
    Requires: pip install geoip2
    Configured via IPGEO["LOCAL_DB_PATH"] in Django settings.
    Returns a geo dict or None.
    """
    from .conf import get as get_conf
    db_path = get_conf("LOCAL_DB_PATH")
    if not db_path:
        return None
    try:
        import geoip2.database  # optional dependency
        with geoip2.database.Reader(db_path) as reader:
            resp = reader.city(ip)
            city = resp.city.name
            if not city:
                return None
            return {
                "city": city,
                "country": resp.country.name,
                "country_code": resp.country.iso_code,
                "lat": resp.location.latitude,
                "lon": resp.location.longitude,
            }
    except Exception as exc:
        logger.debug("ipgeo local DB failed for %s: %s", ip, exc)
        return None


# ---------------------------------------------------------------------------
# Main function — local DB first, then sequential remote fallback
# ---------------------------------------------------------------------------

def geolocate_ip(ip, timeout=2, user_agent="django-ipgeo/1.0"):
    """
    Locate an IP address.

    1. Try the local MaxMind DB (no network). If it returns a result, done.
    2. Query remote services one-by-one and return on the first success.

    Returns dict with keys:
        city, country, country_code, lat, lon, confidence, sources
    or None if nothing worked.
    """
    # --- 1. Local DB ---
    result = _query_local_db(ip)
    if result:
        logger.debug("ipgeo: local DB hit for %s -> %s", ip, result["city"])
        return {**result, "confidence": 1.0, "sources": 1}

    # --- 2. Remote APIs, sequential, stop at first success ---
    for fn in GEO_SERVICES:
        try:
            result = fn(ip, timeout, user_agent)
        except Exception as exc:
            logger.debug("ipgeo service %s raised: %s", fn.__name__, exc)
            continue
        if result:
            logger.debug("ipgeo service %s hit for %s -> %s", fn.__name__, ip, result["city"])
            return {**result, "confidence": 1.0, "sources": 1}
        logger.debug("ipgeo service %s returned nothing for %s", fn.__name__, ip)

    return None
