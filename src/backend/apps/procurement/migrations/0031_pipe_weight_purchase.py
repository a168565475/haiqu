from django.db import migrations, models
from django.db.models import F, Q


class Migration(migrations.Migration):
    dependencies = [("procurement", "0030_purchase_tracking_policy")]

    operations = [
        migrations.AddField(
            model_name="purchaseorderline",
            name="raw_bar_weight_kg",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name="purchaseorderline",
            name="suggested_purchase_weight_kg",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=22, null=True),
        ),
        migrations.AddField(
            model_name="purchaseorderline",
            name="actual_purchase_weight_kg",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=22, null=True),
        ),
        migrations.RemoveConstraint(
            model_name="purchaseorderline",
            name="purchase_pipe_root_meter_consistent",
        ),
        migrations.AddConstraint(
            model_name="purchaseorderline",
            constraint=models.CheckConstraint(
                condition=(Q(raw_bar_length_m__isnull=True, raw_bar_weight_kg__isnull=True,
                             suggested_bar_count__isnull=True, suggested_purchase_meters__isnull=True,
                             suggested_purchase_weight_kg__isnull=True, actual_bar_count__isnull=True,
                             actual_purchase_meters__isnull=True, actual_purchase_weight_kg__isnull=True)
                           | (Q(raw_bar_length_m__isnull=False, raw_bar_length_m__gt=0,
                                 suggested_bar_count__isnull=False, suggested_bar_count__gt=0,
                                 suggested_purchase_meters__isnull=False, source_unit_text="米",
                                 suggested_purchase_meters=F("suggested_bar_count") * F("raw_bar_length_m"))
                               & (Q(actual_bar_count__isnull=True, actual_purchase_meters__isnull=True,
                                    actual_purchase_weight_kg__isnull=True, actual_purchase_quantity__isnull=True)
                                  | Q(actual_bar_count__isnull=False, actual_bar_count__gt=0,
                                      actual_purchase_meters__isnull=False, actual_purchase_quantity__isnull=False,
                                      actual_purchase_meters=F("actual_bar_count") * F("raw_bar_length_m"),
                                      actual_purchase_quantity=F("actual_purchase_meters"))))
                           | (Q(raw_bar_length_m__isnull=False, raw_bar_length_m__gt=0,
                                 raw_bar_weight_kg__isnull=False, raw_bar_weight_kg__gt=0,
                                 suggested_bar_count__isnull=False, suggested_bar_count__gt=0,
                                 suggested_purchase_weight_kg__isnull=False, source_unit_text="KG",
                                 suggested_purchase_weight_kg=F("suggested_bar_count") * F("raw_bar_weight_kg"))
                               & (Q(actual_bar_count__isnull=True, actual_purchase_meters__isnull=True,
                                    actual_purchase_weight_kg__isnull=True, actual_purchase_quantity__isnull=True)
                                  | Q(actual_bar_count__isnull=False, actual_bar_count__gt=0,
                                      actual_purchase_meters__isnull=False, actual_purchase_weight_kg__isnull=False,
                                      actual_purchase_quantity__isnull=False,
                                      actual_purchase_meters=F("actual_bar_count") * F("raw_bar_length_m"),
                                      actual_purchase_quantity=F("actual_purchase_weight_kg"))))
                           | (Q(material_catalog__isnull=False, section_type_snapshot="PROFILE",
                                 raw_bar_length_m__gt=0, suggested_bar_count__gt=0,
                                 suggested_purchase_meters=F("suggested_bar_count") * F("raw_bar_length_m"))
                               & ~Q(source_unit_text="KG")
                               & (Q(actual_bar_count__isnull=True, actual_purchase_meters__isnull=True)
                                  | Q(actual_bar_count__gt=0, actual_purchase_meters=F("actual_bar_count") * F("raw_bar_length_m"))))),
                name="purchase_pipe_root_meter_consistent",
            ),
        ),
        migrations.AddConstraint(
            model_name="purchaseorderline",
            constraint=models.CheckConstraint(
                condition=Q(raw_bar_weight_kg__isnull=True) | Q(raw_bar_weight_kg__gt=0),
                name="purchase_pipe_root_weight_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="purchaseorderline",
            constraint=models.CheckConstraint(
                condition=Q(suggested_purchase_weight_kg__isnull=True) | Q(suggested_purchase_weight_kg__gt=0),
                name="purchase_pipe_suggested_weight_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="purchaseorderline",
            constraint=models.CheckConstraint(
                condition=Q(actual_purchase_weight_kg__isnull=True) | Q(actual_purchase_weight_kg__gt=0),
                name="purchase_pipe_actual_weight_positive",
            ),
        ),
    ]
