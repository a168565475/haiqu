from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("samples", "0032_product_catalog_selection")]

    operations = [
        migrations.AlterField(
            model_name="samplerequest",
            name="customer_account",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="sample_requests", to="customers.customeraccount"),
        ),
    ]
