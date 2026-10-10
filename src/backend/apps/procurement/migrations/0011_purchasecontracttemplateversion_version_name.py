from django.db import migrations, models


def name_existing_versions(apps, schema_editor):
    version_model = apps.get_model("procurement", "PurchaseContractTemplateVersion")
    for version in version_model.objects.all().iterator():
        version.version_name = "初始版" if version.version_number == 1 else f"版本 {version.version_number}"
        version.save(update_fields=["version_name"])


class Migration(migrations.Migration):
    dependencies = [("procurement", "0010_supplierpurchasesheetsealimage")]

    operations = [
        migrations.AddField(
            model_name="purchasecontracttemplateversion",
            name="version_name",
            field=models.CharField(default="初始版", max_length=150),
        ),
        migrations.RunPython(name_existing_versions, migrations.RunPython.noop),
    ]
