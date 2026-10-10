from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("production_tasks", "0013_production_task_yearly_number_rule"),
    ]

    operations = [
        migrations.AlterField(
            model_name="productiontask",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "草稿"),
                    ("PENDING_VALIDATION", "待校验"),
                    ("READY", "已接单"),
                    ("IN_PRODUCTION", "生产中"),
                    ("PAUSED", "已暂停"),
                    ("COMPLETED", "已完成"),
                    ("CANCELLED", "已取消"),
                ],
                default="DRAFT",
                max_length=30,
            ),
        ),
    ]
