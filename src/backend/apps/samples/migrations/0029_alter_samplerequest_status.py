from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('samples', '0028_sample_issue_statuses'),
    ]

    operations = [
        migrations.AlterField(
            model_name='samplerequest',
            name='status',
            field=models.CharField(choices=[('DRAFT', '草稿'), ('DIRECTOR_REVIEW', '待厂长确认'), ('APPLICATION_RETURNED', '退回业务员补充'), ('MATERIALS_PENDING', '待打样部填写'), ('WAREHOUSE_PENDING', '待仓库核对'), ('PROCUREMENT_PENDING', '待采购处理'), ('MATERIALS_READY', '材料已核对齐备'), ('MATERIAL_ISSUE_PENDING', '待发起领料'), ('MATERIAL_ISSUE_REVIEW', '待仓库确认领料'), ('PENDING_COMPLETION', '待工厂完善'), ('PENDING', '财务待确认'), ('PMC_REVIEW', 'PMC待审核'), ('METALWORK_PENDING', '待上传金工参数'), ('CUTTING_PENDING', '待上传裁剪参数'), ('PRODUCTION_PENDING', '待生产完成'), ('FINISHED', '流程已结束'), ('PREPARING', '待寄出'), ('SHIPPED', '运输中'), ('DELIVERED', '已签收'), ('FEEDBACK_PENDING', '待反馈'), ('CONFIRMED', '已确认'), ('COMPLETED', '已确认（历史）'), ('REJECTED', '未通过'), ('CANCELLED', '已取消')], default='DRAFT', max_length=30),
        ),
    ]
