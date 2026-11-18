from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('codex_connection', '0002_remove_codexoperation_codex_operation_action_valid_and_more'),
    ]

    operations = [
        migrations.RemoveConstraint(model_name='codexoperation', name='codex_operation_action_valid'),
        migrations.AlterField(
            model_name='codexoperation', name='action',
            field=models.CharField(choices=[(value, value) for value in
                ('login', 'switch', 'disconnect', 'refresh', 'test', 'discover', 'extract', 'nest')], max_length=12),
        ),
        migrations.AddConstraint(
            model_name='codexoperation',
            constraint=models.CheckConstraint(condition=models.Q(action__in=
                ('login', 'switch', 'disconnect', 'refresh', 'test', 'discover', 'extract', 'nest')),
                name='codex_operation_action_valid'),
        ),
    ]
