from django.apps import AppConfig


class ProcurementConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.procurement"
    verbose_name = "采购管理"

    def ready(self):
        from .tracking_hooks import connect_tracking_hooks

        connect_tracking_hooks()
