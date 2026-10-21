import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0004_fix_communication_link_trigger")]

    operations = [
        migrations.CreateModel(
            name="DailyBusinessNumberCounter",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("number_type", models.CharField(max_length=30, validators=[django.core.validators.RegexValidator(
                    message="编码只能包含大写字母、数字、点、下划线和连字符。", regex="^[A-Z0-9][A-Z0-9._-]*$",
                )])),
                ("business_date", models.DateField()),
                ("last_value", models.PositiveBigIntegerField()),
            ],
            options={
                "db_table": "core_daily_business_number_counter",
                "constraints": [
                    models.UniqueConstraint(fields=("number_type", "business_date"), name="daily_business_number_unique"),
                    models.CheckConstraint(condition=models.Q(last_value__gte=1), name="daily_business_number_positive"),
                ],
            },
        ),
    ]
