import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("organizations", "0002_seed_root_organization")]
    operations = [
        migrations.AlterModelOptions(
            name="organizationunit",
            options={"ordering": ["sort_order", "unit_code"],
                     "permissions": [("manage_organization", "管理部门与组织归属")]},
        ),
        migrations.AddField(
            model_name="roleprofile", name="department",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="roles", to="organizations.organizationunit"),
        ),
    ]
