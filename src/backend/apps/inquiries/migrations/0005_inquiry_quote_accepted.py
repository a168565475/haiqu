from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inquiries", "0004_inquirydraftrevision_and_more"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="inquiry",
            name="inquiry_status_valid",
        ),
        migrations.AlterField(
            model_name="inquiry",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "草稿"),
                    ("NEW", "待确认"),
                    ("ANALYZING", "需求分析中"),
                    ("READY_FOR_QUOTE", "待报价"),
                    ("QUOTING", "报价中"),
                    ("QUOTED", "已报价"),
                    ("FOLLOW_UP", "客户跟进中"),
                    ("QUOTE_ACCEPTED", "报价已接受"),
                    ("CONVERTED", "已创建销售订单"),
                    ("LOST", "已丢失"),
                    ("CLOSED", "已关闭"),
                    ("CANCELLED", "已取消"),
                ],
                default="DRAFT",
                max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name="inquiry",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    status__in=[
                        "DRAFT",
                        "NEW",
                        "ANALYZING",
                        "READY_FOR_QUOTE",
                        "QUOTING",
                        "QUOTED",
                        "FOLLOW_UP",
                        "QUOTE_ACCEPTED",
                        "CONVERTED",
                        "LOST",
                        "CLOSED",
                        "CANCELLED",
                    ]
                ),
                name="inquiry_status_valid",
            ),
        ),
    ]
