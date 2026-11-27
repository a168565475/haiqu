from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("workshop_reporting", "0016_wageschemeline_component_snapshots")]

    operations = [
        migrations.AddField(
            model_name="wageschemeline",
            name="cutting_components",
            field=models.JSONField(blank=True, default=list),
        ),
        *[
            migrations.AlterField(
                model_name=model_name,
                name="counting_mode",
                field=models.CharField(
                    choices=[("ORDER", "按订单量"), ("SET", "按套"), ("PIECE", "按片"), ("GROUP", "按组")],
                    default="ORDER", max_length=12,
                ),
            )
            for model_name in ("wageschemeline", "workitem")
        ],
        migrations.AlterField(
            model_name="wageschemeevent",
            name="action",
            field=models.CharField(
                choices=[("CREATED", "创建"), ("UPDATED", "修改"), ("SUBMITTED", "送审"), ("WITHDRAWN", "撤回"),
                         ("APPROVED", "批准"), ("RETURNED", "退回"), ("CHANGE_CREATED", "发起变更")],
                max_length=24,
            ),
        ),
    ]
