from django.db import migrations, models
import django.db.models.deletion

from apps.core.models import uppercase_code_validator


def copy_container_type_code(apps, schema_editor):
    QuotationContainerTier = apps.get_model("quotations", "QuotationContainerTier")
    for tier in QuotationContainerTier.objects.select_related("container_config").all().iterator():
        tier.container_type_code = tier.container_config.container_type_code
        tier.save(update_fields=["container_type_code"])


class Migration(migrations.Migration):
    dependencies = [
        ("quotations", "0009_seed_fixed_quotation_template"),
    ]

    operations = [
        migrations.AddField(
            model_name="quotationcontainertier",
            name="container_type_code",
            field=models.CharField(default="", max_length=30, validators=[uppercase_code_validator]),
            preserve_default=False,
        ),
        migrations.RunPython(copy_container_type_code, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="quotationcontainertier",
            name="container_config",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="quotation_tiers",
                to="quotations.quotationcontainerconfig",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="quotationcontainertier",
            name="quote_container_tier_config_uniq",
        ),
    ]
