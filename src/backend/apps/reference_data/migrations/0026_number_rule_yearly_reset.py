from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("reference_data", "0025_number_rule_daily_granularity"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="numberrule",
            name="number_rule_reset_policy_valid",
        ),
        migrations.AddConstraint(
            model_name="numberrule",
            constraint=models.CheckConstraint(
                condition=models.Q(reset_policy__in=["NEVER", "DAILY", "YEARLY"]),
                name="number_rule_reset_policy_valid",
            ),
        ),
    ]
