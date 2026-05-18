from django.apps import AppConfig


class IPGeoConfig(AppConfig):
    name = "ipgeo"
    verbose_name = "IP Geolocation"

    def ready(self):
        from .engine import maybe_schedule_db_update
        maybe_schedule_db_update()
