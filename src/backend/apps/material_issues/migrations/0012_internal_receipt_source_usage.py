from django.db import migrations, models
from django.db.models import F, Q


class Migration(migrations.Migration):
    dependencies = [('material_issues', '0011_original_handoff_public_transition')]
    operations = [
        migrations.AddField(model_name='metalprocessingsource', name='internal_received_pieces',
                            field=models.PositiveBigIntegerField(default=0)),
        migrations.RemoveConstraint(model_name='metalprocessingsource', name='metal_source_handoff_limit'),
        migrations.AddConstraint(model_name='metalprocessingsource', constraint=models.CheckConstraint(
            condition=Q(completed_pieces__gte=F('reserved_pieces') + F('dispatched_pieces') + F('internal_received_pieces')),
            name='metal_source_handoff_limit')),
    ]
