"""
Per-IP caching layer in front of the geolocation engine.

Both the middleware and the context processor go through resolve_geo(), so a
request that uses either (or both) triggers at most one lookup.

Results are cached by IP in Django's cache framework rather than in the
session. Keying by IP means one lookup serves every visitor from that address,
and — more importantly — a cookieless client no longer causes a session write.
Crawlers never return a session cookie, so session-backed caching created a new
session row on every single hit.
"""

import logging

from django.core.cache import caches

from .conf import get_config
from .engine import geolocate_ip, get_client_ip, is_private_ip

logger = logging.getLogger(__name__)

# Cached negative result. Distinct from None, which means "not in the cache".
MISS = False


def _cache_key(conf, ip):
    return "%s%s" % (conf["CACHE_KEY_PREFIX"], ip)


def resolve_geo(request):
    """
    Return the geo dict for this request's client IP, or None.

    Looks in (1) the request itself, (2) the session if USE_SESSION is on,
    (3) the cache, and only then hits the engine.
    """
    conf = get_config()

    # 1. Already resolved earlier in this same request.
    geo = getattr(request, "_ipgeo_cached", None)
    if geo is not None:
        return geo or None

    session_key = conf["SESSION_KEY"]
    use_session = conf["USE_SESSION"]

    # 2. Session, only when explicitly enabled.
    if use_session:
        geo = request.session.get(session_key)
        if geo is not None:
            request._ipgeo_cached = geo
            return geo or None

    ip = get_client_ip(request)
    if not ip or is_private_ip(ip):
        request._ipgeo_cached = MISS
        return None

    cache = caches[conf["CACHE_ALIAS"]]
    key = _cache_key(conf, ip)

    # 3. Shared per-IP cache.
    geo = cache.get(key)

    if geo is None:
        geo = geolocate_ip(ip, timeout=conf["TIMEOUT"])
        if geo:
            cache.set(key, geo, conf["CACHE_TIMEOUT"])
            logger.info(
                "ipgeo: %s -> %s, %s (confidence=%.0f%%, sources=%d)",
                ip,
                geo["city"],
                geo["country_code"],
                geo["confidence"] * 100,
                geo["sources"],
            )
        else:
            geo = MISS
            cache.set(key, MISS, conf["CACHE_MISS_TIMEOUT"])

    if use_session:
        request.session[session_key] = geo

    request._ipgeo_cached = geo
    return geo or None
