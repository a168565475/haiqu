from django.apps import AppConfig


class ReferenceDataConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reference_data"
    verbose_name = "公共基础字典"

    def ready(self):
        from django.apps import apps
        from django.db.models.signals import post_delete, post_save
        from .configuration_cache import configuration_changed

        models = list(self.get_models()) + [
            apps.get_model('organizations', 'Employee'),
        ]
        for model in models:
            for signal in (post_save, post_delete):
                signal.connect(configuration_changed, sender=model, weak=False,
                               dispatch_uid=f'configuration_cache:{model._meta.label_lower}')
