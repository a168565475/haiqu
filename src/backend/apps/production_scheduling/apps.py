from django.apps import AppConfig


class ProductionSchedulingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.production_scheduling"
    verbose_name = "生产排产"
