from django.conf import settings

_DEFAULTS = {
    # Engine settings
    "TIMEOUT": 2,
    "SESSION_KEY": "ipgeo",
    # Where per-IP results are cached. The cache is keyed by IP, so the result
    # is shared across every visitor from that address instead of being copied
    # into each one's session.
    #
    # Session storage is opt-in and off by default: cookieless clients (every
    # crawler) get a brand-new session per request, so writing geo data there
    # inserts one session row per hit and will bloat the session store into
    # millions of rows. Only enable it if you need geo pinned to a session.
    "USE_SESSION": False,
    "CACHE_ALIAS": "default",
    # How long a successful lookup stays cached (seconds).
    "CACHE_TIMEOUT": 60 * 60 * 24,
    # How long a failed lookup stays cached (seconds). Without this, every
    # request from an unresolvable IP re-runs the full remote-API fallback.
    "CACHE_MISS_TIMEOUT": 60 * 60,
    "CACHE_KEY_PREFIX": "ipgeo:",
    # Path where the local MaxMind .mmdb file lives (or will be downloaded to).
    "LOCAL_DB_PATH": None,
    # MaxMind license key — if set, the DB is downloaded automatically when
    # missing or older than LOCAL_DB_UPDATE_DAYS days.
    "LOCAL_DB_LICENSE_KEY": None,
    # MaxMind edition to download (default: GeoLite2-City).
    "LOCAL_DB_EDITION": "GeoLite2-City",
    # Re-download the local DB after this many days.
    "LOCAL_DB_UPDATE_DAYS": 60,
    # Public mirror URL — checked before hitting MaxMind directly. The URL is
    # templated with {edition}; default points to ipaddress.world's GeoIP
    # cache (files there expire after 48h). Set to None to disable.
    "CACHE_URL": "https://ipaddress.world/api/geoip-cache/{edition}/",
    # Token required to PUT a fresh .mmdb to the public cache. Set to None to
    # skip the upload step (download still works, others just won't benefit).
    "CACHE_UPLOAD_TOKEN": None,

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
