from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workshop_reporting", "0010_workreport_editing"),
    ]

    operations = [
        migrations.AddField(
            model_name="wageschemeline",
            name="production_description",
            field=models.CharField(blank=True, max_length=500),
        ),
    ]
