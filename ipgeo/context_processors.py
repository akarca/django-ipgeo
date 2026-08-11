"""
Generic model-matching context processor for IP geolocation.

Provides template context with geo data and optional model matches.
Models are resolved via Django's app registry — no hardcoded imports.
"""

import logging

from django.apps import apps

from .cache import resolve_geo
from .conf import get_config

logger = logging.getLogger(__name__)


def _resolve_model(dotted_path):
    """Resolve 'app_label.ModelName' to a Django model class."""
    if not dotted_path:
        return None
    app_label, model_name = dotted_path.rsplit(".", 1)
    return apps.get_model(app_label, model_name)


def _match_instance(model_class, match_strategies, geo_data):
    """
    Try each match strategy in order. Return the first matching instance.

    Each strategy is a dict:
        {"field": "country_code", "lookup": "iexact", "geo_key": "country_code"}
    """
    for strategy in match_strategies:
        geo_value = geo_data.get(strategy["geo_key"])
        if not geo_value:
            continue
        if strategy["geo_key"] == "country_code":
            geo_value = geo_value.upper()
        lookup = f"{strategy['field']}__{strategy['lookup']}"
        instance = model_class.objects.filter(**{lookup: geo_value}).first()
        if instance:
            return instance
    return None


def ipgeo_context(request):
    """
    Context processor: geolocates user IP, matches against configured models,
    and provides template context variables.

    Settings via IPGEO dict in Django settings. See ipgeo.conf for defaults.
    """
    conf = get_config()
    prefix = conf["CONTEXT_PREFIX"]

    # 1. Resolve via the shared per-IP cache (see ipgeo.cache).
    geo = resolve_geo(request)

    # 2. Build model-match context
    matched_city = None
    matched_country = None
    nearby_items = []

    if geo:
        CityModel = _resolve_model(conf["CITY_MODEL"])
        CountryModel = _resolve_model(conf["COUNTRY_MODEL"])

        # City match
        if CityModel:
            matched_city = _match_instance(CityModel, conf["CITY_MATCH"], geo)
            if matched_city and conf["CITY_SELECT_RELATED"]:
                matched_city = (
                    CityModel.objects
                    .filter(pk=matched_city.pk)
                    .select_related(*conf["CITY_SELECT_RELATED"])
                    .first()
                )

        # Country match
        if CountryModel:
            if matched_city and conf.get("NEARBY_FK_TO_COUNTRY"):
                matched_country = getattr(
                    matched_city, conf["NEARBY_FK_TO_COUNTRY"], None,
                )
            if not matched_country:
                matched_country = _match_instance(
                    CountryModel, conf["COUNTRY_MATCH"], geo,
                )

        # Nearby items
        NearbyModel = _resolve_model(conf["NEARBY_MODEL"])
        if NearbyModel and matched_country and conf.get("NEARBY_FK_TO_COUNTRY"):
            qs = NearbyModel.objects.filter(
                **{conf["NEARBY_FK_TO_COUNTRY"]: matched_country},
                **conf["NEARBY_FILTER"],
            )
            if conf["NEARBY_EXCLUDE"]:
                qs = qs.exclude(**conf["NEARBY_EXCLUDE"])
            if conf["NEARBY_SELECT_RELATED"]:
                qs = qs.select_related(*conf["NEARBY_SELECT_RELATED"])
            nearby_items = list(qs[: conf["NEARBY_LIMIT"]])

    return {
        f"{prefix}_data": geo,
        f"{prefix}_city": matched_city,
        f"{prefix}_country": matched_country,
        f"{prefix}_nearby": nearby_items,
    }
