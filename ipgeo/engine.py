"""
IP geolocation engine.

Priority order:
  1. Local MaxMind GeoLite2 DB (if LOCAL_DB_PATH is configured) — no network call.
  2. Remote APIs queried sequentially; returns on first success.

Auto-download: if LOCAL_DB_LICENSE_KEY is set and the DB file is missing or
older than LOCAL_DB_UPDATE_DAYS days, a background thread downloads it from
MaxMind. While the download is in progress the engine falls through to remote
APIs transparently.

Cache: download first tries a public mirror (default: ipaddress.world's
/api/geoip-cache/<edition>/) to avoid MaxMind's daily download limit. On
cache miss it falls through to MaxMind, then re-uploads the fresh file to
the cache so the next consumer benefits.
"""

import ipaddress
import json
import logging
import os
import tarfile
import threading
import time
from urllib.error import HTTPError, URLError
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
# Local DB — auto-download + query
# ---------------------------------------------------------------------------

_download_lock = threading.Lock()
_download_in_progress = False


def _db_needs_update(db_path, update_days):
    """Return True if db_path doesn't exist or is older than update_days."""
    if not os.path.exists(db_path):
        return True
    age_seconds = time.time() - os.path.getmtime(db_path)
    return age_seconds > update_days * 86400


def _http_download(url, dest_path, timeout=120):
    """Stream url -> dest_path. Returns True on success."""
    req = Request(url, headers={"User-Agent": "django-ipgeo/1.0"})
    with urlopen(req, timeout=timeout) as resp, open(dest_path, "wb") as fh:
        while chunk := resp.read(65536):
            fh.write(chunk)
    return True


def _fetch_from_cache(cache_url_template, edition, dest_path):
    """Try the public mirror first. Returns True if a fresh .mmdb was written."""
    if not cache_url_template:
        return False
    cache_url = cache_url_template.format(edition=edition)
    try:
        logger.info("ipgeo: trying cache %s", cache_url)
        tmp = dest_path + ".cache.mmdb"
        _http_download(cache_url, tmp)
        # Sanity-check: real MaxMind mmdb starts with the binary database type
        # marker (0x00 0x01 0x02 0x03 in big-endian). Anything else is almost
        # certainly an HTML error page cached at the edge.
        with open(tmp, "rb") as fh:
            header = fh.read(4)
        if header != b"\x00\x01\x02\x03":
            logger.warning("ipgeo: cache returned non-mmdb payload (header=%r)", header)
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False
        os.replace(tmp, dest_path)
        logger.info("ipgeo: cache hit for %s at %s", edition, dest_path)
        return True
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        logger.info("ipgeo: cache miss for %s (%s)", edition, exc)
        try:
            os.remove(dest_path + ".cache.mmdb")
        except OSError:
            pass
        return False


def _upload_to_cache(cache_url_template, upload_token, edition, source_path):
    """Best-effort upload of source_path to the public cache."""
    if not cache_url_template or not upload_token:
        return
    cache_url = cache_url_template.format(edition=edition)
    try:
        with open(source_path, "rb") as fh:
            req = Request(
                cache_url,
                data=fh.read(),
                method="PUT",
                headers={
                    "User-Agent": "django-ipgeo/1.0",
                    "X-GeoIP-Token": upload_token,
                    "Content-Type": "application/octet-stream",
                },
            )
            urlopen(req, timeout=120).read()
        logger.info("ipgeo: uploaded %s to cache", edition)
    except Exception as exc:
        logger.warning("ipgeo: cache upload failed for %s: %s", edition, exc)


def _download_db(db_path, license_key, edition):
    """
    Download a MaxMind GeoLite2 .mmdb and atomically replace db_path.
    Runs in a background thread — never raises, only logs.
    """
    global _download_in_progress
    from .conf import get as get_conf

    cache_url = get_conf("CACHE_URL")
    upload_token = get_conf("CACHE_UPLOAD_TOKEN")

    tmp_tar = db_path + ".download.tar.gz"
    tmp_mmdb = db_path + ".download.mmdb"
    try:
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

        # --- 1. Cache first ---
        if _fetch_from_cache(cache_url, edition, tmp_mmdb):
            os.replace(tmp_mmdb, db_path)
            logger.info("ipgeo: %s updated from cache at %s", edition, db_path)
            return

        # --- 2. MaxMind ---
        url = (
            f"https://download.maxmind.com/app/geoip_download"
            f"?edition_id={edition}&license_key={license_key}&suffix=tar.gz"
        )
        logger.info("ipgeo: downloading %s from MaxMind...", edition)
        _http_download(url, tmp_tar)

        with tarfile.open(tmp_tar, "r:gz") as tf:
            mmdb_member = next(
                m for m in tf.getmembers() if m.name.endswith(".mmdb")
            )
            with tf.extractfile(mmdb_member) as src, open(tmp_mmdb, "wb") as dst:
                dst.write(src.read())

        os.replace(tmp_mmdb, db_path)
        logger.info("ipgeo: %s updated at %s", edition, db_path)

        # --- 3. Share back to the cache so the next consumer benefits ---
        _upload_to_cache(cache_url, upload_token, edition, db_path)
    except Exception as exc:
        logger.error("ipgeo: failed to download %s: %s", edition, exc)
    finally:
        for f in (tmp_tar, tmp_mmdb):
            try:
                os.remove(f)
            except OSError:
                pass
        with _download_lock:
            _download_in_progress = False


def maybe_schedule_db_update():
    """
    Called at app startup. If the DB is missing or stale and a license key is
    configured, spawn a background thread to download it.
    """
    global _download_in_progress
    from .conf import get as get_conf

    db_path = get_conf("LOCAL_DB_PATH")
    license_key = get_conf("LOCAL_DB_LICENSE_KEY")
    if not db_path or not license_key:
        return

    update_days = get_conf("LOCAL_DB_UPDATE_DAYS")
    if not _db_needs_update(db_path, update_days):
        return

    with _download_lock:
        if _download_in_progress:
            return
        _download_in_progress = True

    edition = get_conf("LOCAL_DB_EDITION")
    t = threading.Thread(
        target=_download_db,
        args=(db_path, license_key, edition),
        daemon=True,
        name="ipgeo-db-download",
    )
    t.start()
    logger.info("ipgeo: started background DB download (thread: %s)", t.name)


def _query_local_db(ip):
    """
    Query the local MaxMind .mmdb file.
    Requires: pip install geoip2
    Returns a geo dict or None (also returns None while a download is in progress).
    """
    from .conf import get as get_conf
    db_path = get_conf("LOCAL_DB_PATH")
    if not db_path or not os.path.exists(db_path):
        # File missing: either first-time download in progress or no DB configured.
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
