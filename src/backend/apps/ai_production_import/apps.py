from django.apps import AppConfig


class AiProductionImportConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai_production_import"
    verbose_name = "AI 生产任务导入"
