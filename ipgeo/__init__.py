"""
django-ipgeo — Parallel IP geolocation for Django.

Queries 5 free geolocation services simultaneously, uses majority voting
to determine the most accurate city. Zero external dependencies beyond Django.
"""

__version__ = "0.1.0"

default_app_config = "ipgeo.apps.IPGeoConfig"
