import uuid

from django.db import migrations


ROOT_ORGANIZATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def seed_root_organization(apps, schema_editor):
    OrganizationUnit = apps.get_model("organizations", "OrganizationUnit")
    OrganizationUnit.objects.get_or_create(
        unit_code="HAIQU",
        defaults={
            "id": ROOT_ORGANIZATION_ID,
            "unit_name": "海趣",
            "status": "ACTIVE",
            "sort_order": 0,
        },
    )


def remove_seeded_root_organization(apps, schema_editor):
    OrganizationUnit = apps.get_model("organizations", "OrganizationUnit")
    OrganizationUnit.objects.filter(id=ROOT_ORGANIZATION_ID, unit_code="HAIQU").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_root_organization, remove_seeded_root_organization),
    ]
