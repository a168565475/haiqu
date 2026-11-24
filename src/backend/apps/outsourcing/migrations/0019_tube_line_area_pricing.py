from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('outsourcing', '0018_plan_record_corrections')]

    operations = [
        migrations.AddField(
            model_name='tubeoutsourcingline',
            name='price_unit',
            field=models.CharField(
                choices=[('PIECE', '按支'), ('SQUARE_METER', '按平方米')],
                default='PIECE',
                db_default='PIECE',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='tubeoutsourcingline',
            name='unit_area_sqm',
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True),
        ),
        migrations.AddConstraint(
            model_name='tubeoutsourcingline',
            constraint=models.CheckConstraint(
                condition=models.Q(price_unit__in=['PIECE', 'SQUARE_METER']),
                name='tube_line_price_unit_valid',
            ),
        ),
        migrations.AddConstraint(
            model_name='tubeoutsourcingline',
            constraint=models.CheckConstraint(
                condition=models.Q(unit_area_sqm__isnull=True) | models.Q(unit_area_sqm__gte=0),
                name='tube_line_area_nonnegative',
            ),
        ),
    ]
