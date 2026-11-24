import sys

from django.apps import AppConfig


def _is_short_lived_command(argv):
    """True for `manage.py <command>` other than runserver: migrate, collectstatic,
    cron jobs... exit within seconds and would cut a background download off. The
    web workers (gunicorn, granian, uwsgi, runserver) start the download instead."""
    return (
        len(argv) > 1
        and argv[0].endswith(("manage.py", "django-admin"))
        and argv[1] != "runserver"
    )


class IPGeoConfig(AppConfig):
    name = "ipgeo"
    verbose_name = "IP Geolocation"

    def ready(self):
        if _is_short_lived_command(sys.argv):
            return
        from .engine import maybe_schedule_db_update
        maybe_schedule_db_update()
