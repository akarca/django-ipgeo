# django-ipgeo

IP geolocation for Django. Resolves visitor IPs to city/country data and
optionally matches them against your own database models.

**Resolution order:**

1. **Local MaxMind GeoLite2-City database** — instant, no network call. Auto-downloaded and refreshed in the background when missing or stale.
2. **Remote APIs (sequential fallback)** — 5 free services tried one-by-one; stops at the first successful response. Used while the local DB is unavailable or not configured.

Result is cached in the Django session — only one lookup per visitor session.

## Features

- Local MaxMind DB with automatic download and 60-day refresh
- Remote fallback to 5 free IP geolocation APIs (no API keys needed)
- Session caching — one lookup per visitor, zero repeat calls
- Generic model matching — attach geo results to any Django Country/City model
- Context processor and optional middleware
- Zero required external dependencies beyond Django (local DB needs `geoip2`)

## Remote Fallback Services

Used only when the local DB is absent or returns no result.

| Service | Rate Limit | API Key |
|---------|-----------|---------|
| ip-api.com | 45 req/min | No |
| ipwho.is | Unlimited | No |
| ipapi.co | 30K/month | No |
| freeipapi.com | Unlimited | No |
| ip2location.io | 30K/day | No |

---

## Installation

```bash
pip install git+ssh://git@github.com/akarca/django-ipgeo.git
```

Or in `requirements.txt`:

```
django-ipgeo @ git+ssh://git@github.com/akarca/django-ipgeo.git
```

For local MaxMind DB support, also install the `geoip2` library:

```bash
pip install geoip2
```

---

## Quick Start

### 1. Add to INSTALLED_APPS

```python
INSTALLED_APPS = [
    ...
    "ipgeo",
]
```

### 2. Add the context processor

```python
TEMPLATES = [
    {
        "OPTIONS": {
            "context_processors": [
                ...
                "ipgeo.context_processors.ipgeo_context",
            ],
        },
    },
]
```

### 3. Configure IPGEO in settings.py

Minimal config (remote-only, no local DB):

```python
IPGEO = {
    "CONTEXT_PREFIX": "geo",
    "COUNTRY_MODEL": "myapp.Country",
    "CITY_MODEL": "myapp.City",
}
```

With local MaxMind DB and auto-download:

```python
import os

IPGEO = {
    "CONTEXT_PREFIX": "geo",
    "COUNTRY_MODEL": "myapp.Country",
    "CITY_MODEL": "myapp.City",

    # Local MaxMind DB — recommended for production
    "LOCAL_DB_PATH": os.path.join(BASE_DIR, "geoip", "GeoLite2-City.mmdb"),
    "LOCAL_DB_LICENSE_KEY": os.environ.get("MAXMIND_API_KEY"),
    "LOCAL_DB_EDITION": "GeoLite2-City",
    "LOCAL_DB_UPDATE_DAYS": 60,
}
```

### 4. Add to .env

```
MAXMIND_API_KEY=your_license_key_here
```

Get a free license key at [maxmind.com](https://www.maxmind.com/en/geolite2/signup) —
create an account and generate a license key for the GeoLite2 free tier.

### 5. Use in templates

```html
{% if geo_nearby %}
<h2>Tours Near You</h2>
{% if geo_city %}
    <p>Discover tours near {{ geo_city.name }}.</p>
{% elif geo_country %}
    <p>Popular tours in {{ geo_country.name }}.</p>
{% endif %}

{% for item in geo_nearby %}
    <a href="{{ item.get_absolute_url }}">{{ item.name }}</a>
{% endfor %}
{% endif %}
```

---

## Settings Reference

All settings go inside the `IPGEO` dict in `settings.py`.

### Engine settings

| Key | Default | Description |
|-----|---------|-------------|
| `TIMEOUT` | `2` | Seconds per remote API call |
| `SESSION_KEY` | `"ipgeo"` | Django session key used to cache the geo result |

### Local MaxMind DB settings

| Key | Default | Description |
|-----|---------|-------------|
| `LOCAL_DB_PATH` | `None` | Absolute path to the `.mmdb` file. If the file doesn't exist and `LOCAL_DB_LICENSE_KEY` is set, it is downloaded automatically. |
| `LOCAL_DB_LICENSE_KEY` | `None` | MaxMind license key. Required for auto-download. Set to `None` to disable auto-download and use only an existing file. Read from environment via `os.environ.get("MAXMIND_API_KEY")`. |
| `LOCAL_DB_EDITION` | `"GeoLite2-City"` | MaxMind edition to download. Change to `"GeoLite2-Country"` for the country-only DB. |
| `LOCAL_DB_UPDATE_DAYS` | `60` | Re-download the DB after this many days. MaxMind releases updates twice a week; 60 days is a reasonable refresh interval. |

**Auto-download behaviour:**

- On Django startup (`AppConfig.ready()`), if `LOCAL_DB_PATH` doesn't exist or is older than `LOCAL_DB_UPDATE_DAYS` days, a background daemon thread downloads the DB from MaxMind.
- The tar.gz is extracted in-memory and the `.mmdb` file is placed at `LOCAL_DB_PATH` via `os.replace()` — the swap is atomic, so no request ever reads a partial file.
- While the first-time download is in progress (file absent), all requests fall through to the remote API fallback transparently.
- While a refresh download is in progress (stale file present), requests continue to use the existing file until the new one lands.

### Model matching settings

| Key | Default | Description |
|-----|---------|-------------|
| `COUNTRY_MODEL` | `None` | Dotted model path, e.g. `"myapp.Country"`. Set to `None` to skip country matching. |
| `COUNTRY_MATCH` | see below | Ordered list of match strategies for country lookup |
| `CITY_MODEL` | `None` | Dotted model path, e.g. `"myapp.City"`. Set to `None` to skip city matching. |
| `CITY_MATCH` | see below | Ordered list of match strategies for city lookup |
| `CITY_SELECT_RELATED` | `[]` | Fields passed to `select_related()` on the city query |
| `NEARBY_MODEL` | `None` | Model for nearby items (typically same as `CITY_MODEL`) |
| `NEARBY_FK_TO_COUNTRY` | `None` | FK field name linking the nearby model to the country |
| `NEARBY_FILTER` | `{}` | Extra `filter()` kwargs for the nearby queryset |
| `NEARBY_EXCLUDE` | `{}` | Extra `exclude()` kwargs for the nearby queryset |
| `NEARBY_SELECT_RELATED` | `[]` | Fields passed to `select_related()` on the nearby query |
| `NEARBY_LIMIT` | `6` | Maximum number of nearby items returned |
| `CONTEXT_PREFIX` | `"ipgeo"` | Prefix for template variable names |

Default `COUNTRY_MATCH`:

```python
[
    {"field": "country_code", "lookup": "iexact", "geo_key": "country_code"},
    {"field": "name",         "lookup": "iexact", "geo_key": "country"},
]
```

Default `CITY_MATCH`:

```python
[
    {"field": "name", "lookup": "iexact", "geo_key": "city"},
]
```

Each strategy dict:

| Key | Description |
|-----|-------------|
| `field` | Model field to filter on |
| `lookup` | Django ORM lookup (e.g. `iexact`, `exact`) |
| `geo_key` | Key from the geo result to use as the filter value. One of: `city`, `country`, `country_code`, `lat`, `lon` |

Strategies are tried in order; the first one that returns a row wins.

---

## Template Variables

The context processor exposes 4 variables. With `CONTEXT_PREFIX = "geo"`:

| Variable | Type | Description |
|----------|------|-------------|
| `geo_data` | `dict` or `None` | Raw geo result: `city`, `country`, `country_code`, `lat`, `lon`, `confidence`, `sources` |
| `geo_city` | model instance or `None` | Matched city from your database |
| `geo_country` | model instance or `None` | Matched country from your database |
| `geo_nearby` | `list` | Nearby items filtered by `NEARBY_FILTER` |

---

## Middleware (Optional)

For access to raw geo data in views:

```python
MIDDLEWARE = [
    ...
    "ipgeo.middleware.IPGeoMiddleware",
]
```

```python
def my_view(request):
    if request.ipgeo:
        city = request.ipgeo["city"]
        country_code = request.ipgeo["country_code"]
```

The middleware only attaches raw geo data. Model matching is handled by the context processor.

---

## Standalone Engine Usage

```python
from ipgeo.engine import geolocate_ip, get_client_ip, is_private_ip

is_private_ip("192.168.1.1")  # True
is_private_ip("8.8.8.8")      # False

result = geolocate_ip("8.8.8.8")
# {
#     "city": "Mountain View",
#     "country": "United States",
#     "country_code": "US",
#     "lat": 37.386,
#     "lon": -122.0838,
#     "confidence": 1.0,
#     "sources": 1
# }
```

---

## How It Works

1. **IP extraction** — reads `X-Forwarded-For`, `X-Real-IP`, or `REMOTE_ADDR`
2. **Private IP check** — skips lookups for localhost/private networks; stores `False` in session
3. **Session cache** — if geo data is already in the session, returns immediately
4. **Local DB** — if `LOCAL_DB_PATH` exists, queries the MaxMind `.mmdb` file (no network); returns on success
5. **Remote fallback** — queries the 5 free APIs sequentially; stops and returns on the first successful response
6. **Auto-refresh** — at startup, if the DB file is absent or older than `LOCAL_DB_UPDATE_DAYS` days, a background thread downloads and atomically replaces it

---

## License

MIT
