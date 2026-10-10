from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("quotations", "0012_quotation_email_dispatch_attempt"),
    ]

    operations = [
        migrations.AddField(
            model_name="quotationline",
            name="color_snapshot",
            field=models.TextField(blank=True, null=True),
        ),
    ]
