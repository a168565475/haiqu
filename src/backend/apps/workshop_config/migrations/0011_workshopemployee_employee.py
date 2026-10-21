import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0003_role_department"),
        ("workshop_config", "0010_craft_embroidery"),
    ]

    operations = [
        migrations.AddField(
            model_name="workshopemployee",
            name="employee",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="workshop_assignments", to="organizations.employee",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="workshopemployee", name="workshop_employee_business_unique",
        ),
        migrations.AddConstraint(
            model_name="workshopemployee",
            constraint=models.UniqueConstraint(
                fields=("workshop", "position", "name"), condition=models.Q(employee__isnull=True),
                name="workshop_emp_unlinked_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="workshopemployee",
            constraint=models.UniqueConstraint(
                fields=("workshop", "position", "employee"), condition=models.Q(employee__isnull=False),
                name="workshop_emp_linked_unique",
            ),
        ),
    ]
