from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0009_customercomplaint_permissions"),
    ]

    operations = [
        migrations.AddField(
            model_name="customeraccount",
            name="legacy_source_data",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="customercontact",
            name="legacy_source_data",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
