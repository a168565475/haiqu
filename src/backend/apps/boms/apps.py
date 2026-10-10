from django.apps import AppConfig


class BomsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.boms"
    verbose_name = "BOM 管理"

    def ready(self):
        from . import signals  # noqa: F401
