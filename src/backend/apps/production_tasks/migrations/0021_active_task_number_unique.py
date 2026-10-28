from django.db import migrations, models

from apps.core.models import uppercase_code_validator


class Migration(migrations.Migration):
    dependencies = [
        ("production_tasks", "0020_production_task_expense"),
    ]

    operations = [
        migrations.AlterField(
            model_name="productiontask",
            name="task_number",
            field=models.CharField(db_index=True, max_length=50, validators=[uppercase_code_validator]),
        ),
        migrations.AddConstraint(
            model_name="productiontask",
            constraint=models.UniqueConstraint(
                fields=("task_number",), condition=models.Q(archived_at__isnull=True),
                name="prod_task_active_number_uniq",
            ),
        ),
    ]
