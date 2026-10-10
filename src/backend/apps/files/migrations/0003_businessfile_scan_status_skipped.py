from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("files", "0002_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="businessfile",
            name="scan_status",
            field=models.CharField(
                choices=[
                    ("PENDING", "待扫描"),
                    ("CLEAN", "安全"),
                    ("INFECTED", "风险文件"),
                    ("FAILED", "扫描失败"),
                    ("SKIPPED", "已跳过"),
                ],
                default="PENDING",
                max_length=20,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="businessfile",
            name="business_file_scan_status_valid",
        ),
        migrations.AddConstraint(
            model_name="businessfile",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    scan_status__in=["PENDING", "CLEAN", "INFECTED", "FAILED", "SKIPPED"]
                ),
                name="business_file_scan_status_valid",
            ),
        ),
    ]
