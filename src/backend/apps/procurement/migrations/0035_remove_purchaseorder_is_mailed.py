from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("procurement", "0034_purchase_group_bom_sources")]

    operations = [
        migrations.RemoveField(model_name="purchaseorder", name="is_mailed"),
    ]
