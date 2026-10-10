from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0004_material_inbound"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="materialinbound",
            options={
                "ordering": ["-inbound_date", "-created_at", "-id"],
                "permissions": [
                    ("receive_material", "Can receive material inventory"),
                    ("view_material_receipt", "Can view material receipt details"),
                ],
            },
        ),
    ]
