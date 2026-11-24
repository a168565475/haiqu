from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("finance", "0009_purchase_payables")]

    operations = [
        migrations.AddField(
            model_name="purchasepayable",
            name="tax_mode",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name="purchasepayable",
            name="freight_mode",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name="purchasepayableline",
            name="tax_mode",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name="purchasepayableline",
            name="freight_mode",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
    ]
