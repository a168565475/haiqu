import uuid
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventory", "0016_materialinbound_stock_mode_and_more"),
                    ("organizations", "0002_seed_root_organization")]
    operations = [migrations.CreateModel(
        name="PublicStockCutoverControl",
        fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
            ("key", models.CharField(default="PUBLIC_STOCK", editable=False, max_length=30, unique=True)),
            ("state", models.CharField(choices=[("MAINTENANCE", "切换停写"), ("PUBLIC", "公共库存")], max_length=20)),
            ("reason", models.TextField()),
            ("started_at", models.DateTimeField(default=django.utils.timezone.now)),
            ("activated_at", models.DateTimeField(blank=True, null=True)),
            ("activation_manifest_sha256", models.CharField(blank=True, max_length=64)),
            ("started_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                            related_name="stock_cutovers_started", to="organizations.employee")),
            ("activated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                              related_name="stock_cutovers_activated", to="organizations.employee")),
        ],
        options={"db_table": "inventory_public_stock_cutover_control", "constraints": [
            models.CheckConstraint(condition=models.Q(key="PUBLIC_STOCK"), name="inv_pub_cutover_singleton"),
            models.CheckConstraint(condition=models.Q(state__in=["MAINTENANCE", "PUBLIC"]), name="inv_pub_cutover_state"),
        ]},
    )]
