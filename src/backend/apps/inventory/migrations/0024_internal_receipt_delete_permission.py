from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('inventory', '0023_alter_finishedgoodsreceipt_options_and_more')]

    operations = [
        migrations.AlterModelOptions(
            name='internalsemifinishedreceipt',
            options={
                'default_permissions': ('add', 'view', 'delete'),
                'ordering': ['-receipt_date', '-created_at', '-id'],
                'permissions': (('confirm_internalsemifinishedreceipt', '确认厂内半成品入库'),),
            },
        ),
    ]
