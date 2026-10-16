from decimal import Decimal
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('production_tasks', '0018_productiontask_tax_rate'),
        ('reference_data', '0028_fill_supplemental_accessory_units'),
    ]
    operations = [
        migrations.AlterField(model_name='productiontaskproduct', name='exchange_rate', field=models.DecimalField(max_digits=25, decimal_places=8, validators=[django.core.validators.MinValueValidator(Decimal('0.00000001'))])),
        migrations.AlterField(model_name='productiontaskproduct', name='product_number_snapshot', field=models.CharField(max_length=100, blank=True)),
        migrations.AlterField(model_name='productiontaskproduct', name='item_number_snapshot', field=models.CharField(max_length=100, blank=True)),
        migrations.AddField(model_name='productiontaskproduct', name='exchange_rate_record', field=models.ForeignKey(to='reference_data.exchangerate', on_delete=django.db.models.deletion.PROTECT, null=True, blank=True, related_name='production_task_products')),
        migrations.AddField(model_name='productiontaskproduct', name='exchange_rate_snapshot', field=models.JSONField(default=dict, blank=True)),
    ]
