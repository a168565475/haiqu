from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("wecom", "0005_directory_snapshot")]

    operations = [
        migrations.AddField(
            model_name="wecombinding",
            name="department_snapshot",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
