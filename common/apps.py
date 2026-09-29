from django.apps import AppConfig


class CommonConfig(AppConfig):
    name = "common"

    def ready(self):
        from . import checks  # noqa: F401
