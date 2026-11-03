from django.db import migrations, models
from django.db.models import F, Q
from django.db.models.functions import Floor


class Migration(migrations.Migration):
    dependencies = [
        ("material_issues", "0015_allow_outsourcing_plan_overage"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="ordermaterialrequirement",
            name="mat_req_pipe_counts_valid",
        ),
        migrations.AddConstraint(
            model_name="ordermaterialrequirement",
            constraint=models.CheckConstraint(
                condition=Q(measurement_kind="OTHER") | Q(
                    required_quantity=Floor(F("required_quantity")),
                    internal_issued_quantity=Floor(F("internal_issued_quantity")),
                    outsourcing_issued_quantity=Floor(F("outsourcing_issued_quantity")),
                ),
                name="mat_req_pipe_counts_valid",
            ),
        ),
    ]
