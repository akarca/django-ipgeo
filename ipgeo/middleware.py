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

from .cache import resolve_geo

logger = logging.getLogger(__name__)


class IPGeoMiddleware:
    """Middleware that attaches geolocation data to the request object."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.ipgeo = resolve_geo(request)

        return self.get_response(request)
