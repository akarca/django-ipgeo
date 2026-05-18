from django.conf import settings

_DEFAULTS = {
    # Engine settings
    "TIMEOUT": 2,
    "SESSION_KEY": "ipgeo",
    # Path where the local MaxMind .mmdb file lives (or will be downloaded to).
    "LOCAL_DB_PATH": None,
    # MaxMind license key — if set, the DB is downloaded automatically when
    # missing or older than LOCAL_DB_UPDATE_DAYS days.
    "LOCAL_DB_LICENSE_KEY": None,
    # MaxMind edition to download (default: GeoLite2-City).
    "LOCAL_DB_EDITION": "GeoLite2-City",
    # Re-download the local DB after this many days.
    "LOCAL_DB_UPDATE_DAYS": 60,

    # Country model matching (set to None to disable)
    "COUNTRY_MODEL": None,
    "COUNTRY_MATCH": [
        {"field": "country_code", "lookup": "iexact", "geo_key": "country_code"},
        {"field": "name", "lookup": "iexact", "geo_key": "country"},
    ],

    # City model matching (set to None to disable)
    "CITY_MODEL": None,
    "CITY_MATCH": [
        {"field": "name", "lookup": "iexact", "geo_key": "city"},
    ],
    "CITY_SELECT_RELATED": [],

    # Nearby / related items query (set to None to disable)
    "NEARBY_MODEL": None,
    "NEARBY_FK_TO_COUNTRY": None,
    "NEARBY_FILTER": {},
    "NEARBY_EXCLUDE": {},
    "NEARBY_SELECT_RELATED": [],
    "NEARBY_LIMIT": 6,

    # Template variable prefix
    "CONTEXT_PREFIX": "ipgeo",
}


def get_config():
    """Return the merged config: user settings override defaults."""
    user = getattr(settings, "IPGEO", {})
    merged = {}
    for key, default in _DEFAULTS.items():
        merged[key] = user.get(key, default)
    return merged


def get(key):
    """Get a single config value."""
    user = getattr(settings, "IPGEO", {})
    return user.get(key, _DEFAULTS.get(key))
