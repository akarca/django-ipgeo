from django.conf import settings

_DEFAULTS = {
    # Engine settings
    "TIMEOUT": 2,
    "SESSION_KEY": "ipgeo",
    # Path to a local MaxMind GeoLite2-City (.mmdb) database file.
    # If set and the DB returns a result, no remote API calls are made.
    "LOCAL_DB_PATH": None,

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
