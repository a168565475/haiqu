import uuid

from django.db import migrations, models


def seed_tube_calculation_formulas(apps, schema_editor):
    formula_model = apps.get_model("reference_data", "TubeCalculationFormula")
    formulas = (
        ("ROUND", "直径*3.14*管材长度/1000000", "(直径-壁厚)*壁厚*3.14*7.854*管材长度/1000000"),
        ("RECTANGULAR", "(截面长+截面宽)*2*管材长度/1000000", "((截面长+截面宽)*2/3.14-壁厚)*壁厚*3.14*7.854*管材长度/1000000"),
        ("OVAL", "截面长/2*截面宽/2*3.14*管材长度/1000000", "(截面长*截面宽-(截面长-2*壁厚)*(截面宽-2*壁厚))/4*3.14*7.854*管材长度/1000000"),
    )
    for group_key, area_expression, weight_expression in formulas:
        formula_model.objects.using(schema_editor.connection.alias).create(
            group_key=group_key, area_expression=area_expression, weight_expression=weight_expression,
        )


class Migration(migrations.Migration):
    dependencies = [("reference_data", "0029_shared_daily_number_rules")]

    operations = [
        migrations.CreateModel(
            name="TubeCalculationFormula",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("group_key", models.CharField(choices=[("ROUND", "圆管"), ("RECTANGULAR", "方管 / 矩形管"), ("OVAL", "椭圆管 / 扁圆管")], max_length=20, unique=True)),
                ("area_expression", models.CharField(max_length=500)),
                ("weight_expression", models.CharField(max_length=500)),
            ],
            options={
                "db_table": "reference_tube_calculation_formula",
                "ordering": ["group_key"],
                "default_permissions": (),
                "constraints": [models.CheckConstraint(condition=models.Q(group_key__in=["ROUND", "RECTANGULAR", "OVAL"]), name="tube_formula_group_valid")],
            },
        ),
        migrations.RunPython(seed_tube_calculation_formulas, migrations.RunPython.noop),
    ]
