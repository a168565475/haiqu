from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("samples", "0027_sample_material_issue"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="samplerequest",
            name="sample_request_status_valid",
        ),
        migrations.AddConstraint(
            model_name="samplerequest",
            constraint=models.CheckConstraint(
                condition=models.Q(status__in=[
                    "DRAFT", "DIRECTOR_REVIEW", "APPLICATION_RETURNED", "MATERIALS_PENDING",
                    "WAREHOUSE_PENDING", "PROCUREMENT_PENDING", "MATERIALS_READY",
                    "MATERIAL_ISSUE_PENDING", "MATERIAL_ISSUE_REVIEW", "PENDING_COMPLETION",
                    "PENDING", "PMC_REVIEW", "METALWORK_PENDING", "CUTTING_PENDING",
                    "PRODUCTION_PENDING", "FINISHED", "PREPARING", "SHIPPED", "DELIVERED",
                    "FEEDBACK_PENDING", "CONFIRMED", "COMPLETED", "REJECTED", "CANCELLED",
                ]),
                name="sample_request_status_valid",
            ),
        ),
    ]
