from django.db import migrations


FORWARD_SQL = """
CREATE OR REPLACE FUNCTION haiqu_guard_quotation_line()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    old_parent_status varchar;
    new_parent_status varchar;
    product_fields text[] := ARRAY[
        'product_id', 'product_category_id', 'product_unit_id', 'product_color_id',
        'product_number_snapshot', 'product_code_snapshot', 'item_number_snapshot',
        'product_description_snapshot', 'specification_snapshot', 'color_snapshot',
        'material_snapshot', 'unit_code', 'updated_at'
    ];
BEGIN
    -- BOM 的事务标记不能放开商业字段、图片、来源关系、其他行或增删操作。
    IF TG_OP = 'UPDATE'
       AND current_setting('haiqu.bom_product_writeback_line', true) = OLD.id::text
       AND (to_jsonb(NEW) - product_fields) = (to_jsonb(OLD) - product_fields) THEN
        RETURN NEW;
    END IF;

    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT status INTO old_parent_status
        FROM quotation_version WHERE id = OLD.quotation_version_id;
        IF old_parent_status <> 'DRAFT' THEN
            RAISE EXCEPTION 'lines of a locked quotation version are immutable'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        SELECT status INTO new_parent_status
        FROM quotation_version WHERE id = NEW.quotation_version_id;
        IF new_parent_status <> 'DRAFT' THEN
            RAISE EXCEPTION 'lines can only be changed while the quotation version is draft'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN NEW;
    END IF;
    RETURN OLD;
END;
$$;
"""

REVERSE_SQL = """
CREATE OR REPLACE FUNCTION haiqu_guard_quotation_line()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    old_parent_status varchar;
    new_parent_status varchar;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT status INTO old_parent_status
        FROM quotation_version WHERE id = OLD.quotation_version_id;
        IF old_parent_status <> 'DRAFT' THEN
            RAISE EXCEPTION 'lines of a locked quotation version are immutable'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        SELECT status INTO new_parent_status
        FROM quotation_version WHERE id = NEW.quotation_version_id;
        IF new_parent_status <> 'DRAFT' THEN
            RAISE EXCEPTION 'lines can only be changed while the quotation version is draft'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN NEW;
    END IF;
    RETURN OLD;
END;
$$;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_fix_communication_link_trigger"),
        ("quotations", "0014_quotationline_item_number_snapshot_and_more"),
    ]

    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
