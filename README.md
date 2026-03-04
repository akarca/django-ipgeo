# django-ipgeo

Parallel IP geolocation for Django. Queries 5 free geolocation services simultaneously, uses majority voting for accuracy. Zero external dependencies beyond Django.

## Features

- **5 free IP geolocation services** queried in parallel (2s timeout)
- **Majority voting** — the most agreed-upon city wins
- **Session caching** — one API round-trip per session, instant on subsequent pages
- **Generic model matching** — works with any Django model via settings
- **Context processor + middleware** — use in templates or views
- **Zero dependencies** — only Django + Python stdlib

## Services Used

| Service | Rate Limit | API Key |
|---------|-----------|---------|
| ip-api.com | 45 req/min | No |
| ipwho.is | Unlimited | No |
| ipapi.co | 30K/month | No |
| freeipapi.com | Unlimited | No |
| ip2location.io | 30K/day | No |

## Installation

```bash
pip install git+ssh://git@github.com/akarca/django-ipgeo.git
```

Or add to your requirements file:

```
django-ipgeo @ git+ssh://git@github.com/akarca/django-ipgeo.git
```

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

### 3. Configure IPGEO settings

```python
IPGEO = {
    "COUNTRY_MODEL": "myapp.Country",
    "CITY_MODEL": "myapp.City",
    "CITY_SELECT_RELATED": ["country"],
    "NEARBY_MODEL": "myapp.City",
    "NEARBY_FK_TO_COUNTRY": "country",
    "NEARBY_FILTER": {"is_featured": True},
    "NEARBY_EXCLUDE": {"image": ""},
    "NEARBY_SELECT_RELATED": ["country"],
    "NEARBY_LIMIT": 6,
    "CONTEXT_PREFIX": "geo",
}
```

### 4. Use in templates

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

## Template Variables

The context processor provides 4 variables, prefixed with `CONTEXT_PREFIX` (default: `ipgeo`):

| Variable | Type | Description |
|----------|------|-------------|
| `{prefix}_data` | `dict` or `None` | Raw geo result: `city`, `country`, `country_code`, `lat`, `lon`, `confidence`, `sources` |
| `{prefix}_city` | model instance or `None` | Matched city from your database |
| `{prefix}_country` | model instance or `None` | Matched country from your database |
| `{prefix}_nearby` | `list` | Nearby items (filtered by `NEARBY_FILTER`) |

## Settings Reference

All settings go inside the `IPGEO` dict in your Django settings:

```python
IPGEO = { ... }
```

| Key | Default | Description |
|-----|---------|-------------|
| `TIMEOUT` | `2` | Seconds per geolocation service |
| `SESSION_KEY` | `"ipgeo"` | Session key for caching geo result |
| `COUNTRY_MODEL` | `None` | Country model path, e.g. `"myapp.Country"` |
| `COUNTRY_MATCH` | `[{field: "country_code", ...}, {field: "name", ...}]` | Ordered list of match strategies for country |
| `CITY_MODEL` | `None` | City model path, e.g. `"myapp.City"` |
| `CITY_MATCH` | `[{field: "name", lookup: "iexact", geo_key: "city"}]` | Match strategies for city |
| `CITY_SELECT_RELATED` | `[]` | `select_related` fields for city query |
| `NEARBY_MODEL` | `None` | Model for nearby items (usually same as city) |
| `NEARBY_FK_TO_COUNTRY` | `None` | FK field name linking nearby model to country |
| `NEARBY_FILTER` | `{}` | Extra filter kwargs for nearby query |
| `NEARBY_EXCLUDE` | `{}` | Extra exclude kwargs for nearby query |
| `NEARBY_SELECT_RELATED` | `[]` | `select_related` fields for nearby query |
| `NEARBY_LIMIT` | `6` | Max nearby items returned |
| `CONTEXT_PREFIX` | `"ipgeo"` | Prefix for template variable names |

### Match Strategies

`COUNTRY_MATCH` and `CITY_MATCH` are lists of strategy dicts, tried in order until one matches:

```python
{
    "field": "country_code",  # Model field to filter on
    "lookup": "iexact",       # Django ORM lookup type
    "geo_key": "country_code" # Key from geo result dict to use as value
}
```

Available `geo_key` values: `city`, `country`, `country_code`, `lat`, `lon`.

## Middleware (Optional)

For access to geo data in views (not just templates):

```python
MIDDLEWARE = [
    ...
    "ipgeo.middleware.IPGeoMiddleware",
]
```

Then in views:

```python
def my_view(request):
    if request.ipgeo:
        city = request.ipgeo["city"]
        country_code = request.ipgeo["country_code"]
```

The middleware only provides raw geo data. Model matching is handled by the context processor.

## Standalone Engine Usage

You can use the geolocation engine without Django integration:

```python
from ipgeo.engine import geolocate_ip, get_client_ip, is_private_ip

# Check if IP is private
is_private_ip("192.168.1.1")  # True
is_private_ip("8.8.8.8")      # False

# Geolocate an IP
result = geolocate_ip("8.8.8.8")
# {
#     "city": "Mountain View",
#     "country": "United States",
#     "country_code": "US",
#     "lat": 37.386,
#     "lon": -122.0838,
#     "confidence": 0.8,
#     "sources": 5
# }
```

## How It Works

1. **IP extraction** — reads `X-Forwarded-For`, `X-Real-IP`, or `REMOTE_ADDR`
2. **Private IP check** — skips API calls for localhost/private networks
3. **Parallel query** — `ThreadPoolExecutor` queries all 5 services with 2s timeout
4. **Majority voting** — `Counter` finds the most agreed-upon city name (case-insensitive)
5. **Confidence score** — `votes / total_responses` (e.g., 4/5 = 0.8)
6. **Session cache** — result stored in Django session, no repeat API calls

## License

MIT
