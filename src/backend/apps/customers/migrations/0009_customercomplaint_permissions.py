from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("customers", "0008_customercomplaint_customercomplaintprogress_and_more"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="customercomplaint",
            options={
                "ordering": ["-updated_at", "-id"],
                "permissions": [
                    ("process_customer_complaint", "可处理客诉"),
                    ("close_customer_complaint", "可关闭客诉"),
                ],
            },
        ),
    ]
