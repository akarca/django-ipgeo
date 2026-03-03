"""
Parallel IP geolocation engine.

Queries 5 free services simultaneously, returns majority-voted city.
No external dependencies — uses only Python standard library.
"""

import ipaddress
import json
import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
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
# Main function — parallel execution with majority voting
# ---------------------------------------------------------------------------

def geolocate_ip(ip, timeout=2, user_agent="django-ipgeo/1.0"):
    """
    Query all geolocation services in parallel, aggregate by majority vote.

    Returns dict with keys:
        city, country, country_code, lat, lon, confidence, sources
    or None if no service returned a result.
    """
    results = []

    with ThreadPoolExecutor(max_workers=len(GEO_SERVICES)) as executor:
        futures = {
            executor.submit(fn, ip, timeout, user_agent): fn.__name__
            for fn in GEO_SERVICES
        }
        for future in as_completed(futures, timeout=timeout + 1):
            name = futures[future]
            try:
                result = future.result(timeout=0.1)
                if result:
                    results.append(result)
                    logger.debug("ipgeo service %s returned: %s", name, result["city"])
            except Exception as exc:
                logger.debug("ipgeo service %s failed: %s", name, exc)

    if not results:
        return None

    # Majority vote on city name (case-insensitive)
    city_counter = Counter(r["city"].lower() for r in results)
    best_city_lower, vote_count = city_counter.most_common(1)[0]

    # Pick the first result matching the winning city for full data
    winning = next(r for r in results if r["city"].lower() == best_city_lower)

    return {
        "city": winning["city"],
        "country": winning["country"],
        "country_code": winning["country_code"],
        "lat": winning["lat"],
        "lon": winning["lon"],
        "confidence": round(vote_count / len(results), 2),
        "sources": len(results),
    }
