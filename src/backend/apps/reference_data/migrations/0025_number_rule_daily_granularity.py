from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("reference_data", "0024_correct_tube_length_pinyin"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="numberrule",
            name="number_rule_date_granularity_valid",
        ),
        migrations.RemoveConstraint(
            model_name="numberrule",
            name="number_rule_reset_policy_valid",
        ),
        migrations.AlterField(
            model_name="numberrule",
            name="date_granularity",
            field=models.CharField(
                choices=[
                    ("NONE", "不含日期"),
                    ("YEAR", "按年展示"),
                    ("MONTH", "按月展示"),
                    ("DAY", "按日展示"),
                ],
                default="NONE",
                max_length=10,
            ),
        ),
        migrations.AddConstraint(
            model_name="numberrule",
            constraint=models.CheckConstraint(
                condition=models.Q(date_granularity__in=["NONE", "YEAR", "MONTH", "DAY"]),
                name="number_rule_date_granularity_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="numberrule",
            constraint=models.CheckConstraint(
                condition=models.Q(reset_policy__in=["NEVER", "DAILY"]),
                name="number_rule_reset_policy_valid",
            ),
        ),
    ]
