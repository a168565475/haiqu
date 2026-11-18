from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("boms", "0019_pipe_meter_precision")]

    operations = [
        migrations.AddField(model_name="bomline", name="component_kind",
            field=models.CharField(blank=True, default="", max_length=20,
                choices=[("", "历史用料"), ("CUT_PIECE", "裁片"), ("SEWN_PART", "车缝部位")])),
        migrations.AddField(model_name="bomline", name="parent_part",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="cut_pieces", to="boms.bomline")),
        migrations.AddField(model_name="bomline", name="pieces_per_part",
            field=models.PositiveBigIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="bomline", name="parts_per_product",
            field=models.PositiveBigIntegerField(blank=True, null=True)),
        migrations.AddConstraint(model_name="bomline", constraint=models.CheckConstraint(
            condition=models.Q(component_kind__in=["", "CUT_PIECE", "SEWN_PART"]), name="bom_component_kind_valid")),
        migrations.AddConstraint(model_name="bomline", constraint=models.CheckConstraint(
            condition=models.Q(pieces_per_part__isnull=True) | models.Q(pieces_per_part__gt=0),
            name="bom_pieces_per_part_positive")),
        migrations.AddConstraint(model_name="bomline", constraint=models.CheckConstraint(
            condition=models.Q(parts_per_product__isnull=True) | models.Q(parts_per_product__gt=0),
            name="bom_parts_per_product_positive")),
        migrations.AddConstraint(model_name="bomline", constraint=models.CheckConstraint(
            condition=(models.Q(component_kind="CUT_PIECE", parts_per_product__isnull=True)
                | models.Q(component_kind="SEWN_PART", parent_part__isnull=True, pieces_per_part__isnull=True)
                | models.Q(component_kind="", parent_part__isnull=True, pieces_per_part__isnull=True,
                           parts_per_product__isnull=True)), name="bom_component_fields_match_kind")),
    ]
