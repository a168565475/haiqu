from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('workshop_config', '0002_fixed_workshops'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='workshop',
            constraint=models.CheckConstraint(
                condition=models.Q(name__in=('金工车间', '车缝车间', '装配车间', '敲布孔')),
                name='workshop_name_fixed',
            ),
        ),
        migrations.AddConstraint(
            model_name='workshop',
            constraint=models.CheckConstraint(
                condition=models.Q(status='ACTIVE'),
                name='workshop_always_active',
            ),
        ),
    ]
