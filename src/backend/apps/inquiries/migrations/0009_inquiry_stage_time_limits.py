from django.db import migrations


def enable_stage_limits(apps, schema_editor):
    Policy = apps.get_model('workflow', 'SlaPolicy')
    policy = Policy.objects.using(schema_editor.connection.alias).filter(policy_code='INQUIRY_WORKTIME_202609').first()
    if policy is None:
        raise RuntimeError('请先安装询盘大小周工作时间规则。')
    config = dict(policy.config_data)
    config['stage_minutes'] = {'ASSIGNMENT': 30, 'QUOTE_CREATION': 60, 'QUOTE_DELIVERY': 240,
                               'CUSTOMER_FOLLOW_UP': 450, 'POST_ACCEPTANCE': 120, 'SAMPLE_FOLLOW_UP': 450}
    policy.config_data = config
    policy.save(update_fields=['config_data'])


class Migration(migrations.Migration):
    dependencies = [('inquiries', '0008_inquiry_worktime_policy')]
    operations = [migrations.RunPython(enable_stage_limits, migrations.RunPython.noop)]
