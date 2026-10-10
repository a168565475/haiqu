from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("workshop_reporting", "0005_wagescheme_operation_product_name_snapshot")]

    operations = [
        migrations.AddConstraint(
            model_name="wagescheme",
            constraint=models.UniqueConstraint(
                fields=("parent_scheme", "version"),
                condition=Q(parent_scheme__isnull=False),
                name="wage_scheme_parent_version_unique",
            ),
        ),
    ]
