"""
Optional middleware for view-level access to IP geolocation data.

Sets request.ipgeo with the raw geolocation dict (or None).
Does NOT do model matching — use the context processor for that.

Usage in settings.py:
    MIDDLEWARE = [
        ...
        "ipgeo.middleware.IPGeoMiddleware",
        ...
    ]

Then in views:
    def my_view(request):
        if request.ipgeo:
            city = request.ipgeo["city"]
"""

import logging

from .conf import get_config
from .engine import get_client_ip, geolocate_ip, is_private_ip

logger = logging.getLogger(__name__)


class IPGeoMiddleware:
    """Middleware that attaches geolocation data to the request object."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        conf = get_config()
        session_key = conf["SESSION_KEY"]

        geo = request.session.get(session_key)

        if geo is None:
            ip = get_client_ip(request)
            if ip and not is_private_ip(ip):
                geo = geolocate_ip(ip, timeout=conf["TIMEOUT"])
                if geo:
                    request.session[session_key] = geo
                    logger.info(
                        "ipgeo: %s -> %s, %s (confidence=%.0f%%, sources=%d)",
                        ip,
                        geo["city"],
                        geo["country_code"],
                        geo["confidence"] * 100,
                        geo["sources"],
                    )
                else:
                    request.session[session_key] = False
                    geo = False
            else:
                request.session[session_key] = False
                geo = False

        request.ipgeo = geo if geo and geo is not False else None

        return self.get_response(request)
