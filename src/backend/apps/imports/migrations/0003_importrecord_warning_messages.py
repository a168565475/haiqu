from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0002_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="importrecord",
            name="warning_messages",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
