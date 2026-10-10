from django.db import migrations


FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION ps_touch_parent_schedule() RETURNS trigger AS $$
DECLARE
    old_schedule_id uuid;
    new_schedule_id uuid;
BEGIN
    IF TG_TABLE_NAME = 'production_schedule_product' THEN
        IF TG_OP <> 'INSERT' THEN old_schedule_id := OLD.schedule_id; END IF;
        new_schedule_id := NEW.schedule_id;
    ELSE
        IF TG_OP <> 'INSERT' THEN
            SELECT schedule_id INTO old_schedule_id
            FROM production_schedule_product WHERE id = OLD.schedule_product_id;
        END IF;
        SELECT schedule_id INTO new_schedule_id
        FROM production_schedule_product WHERE id = NEW.schedule_product_id;
    END IF;
    IF old_schedule_id IS NOT NULL THEN
        UPDATE production_schedule
        SET version = version + 1, updated_at = clock_timestamp()
        WHERE id = old_schedule_id;
    END IF;
    IF new_schedule_id IS DISTINCT FROM old_schedule_id THEN
        UPDATE production_schedule
        SET version = version + 1, updated_at = clock_timestamp()
        WHERE id = new_schedule_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ps_schedule_product_touch_parent
AFTER INSERT OR UPDATE ON production_schedule_product
FOR EACH ROW EXECUTE FUNCTION ps_touch_parent_schedule();
CREATE TRIGGER ps_schedule_craft_touch_parent
AFTER INSERT OR UPDATE ON production_schedule_product_craft
FOR EACH ROW EXECUTE FUNCTION ps_touch_parent_schedule();

CREATE OR REPLACE FUNCTION ps_validate_schedule_craft_row() RETURNS trigger AS $$
DECLARE
    parent_removed_at timestamptz;
    source_type varchar(20);
    source_name varchar(100);
    source_category varchar(20);
BEGIN
    SELECT removed_at INTO parent_removed_at
    FROM production_schedule_product WHERE id = NEW.schedule_product_id FOR KEY SHARE;
    IF TG_OP = 'INSERT'
       OR NEW.schedule_product_id IS DISTINCT FROM OLD.schedule_product_id
       OR NEW.craft_id IS DISTINCT FROM OLD.craft_id
       OR NEW.craft_type_snapshot IS DISTINCT FROM OLD.craft_type_snapshot
       OR NEW.craft_name_snapshot IS DISTINCT FROM OLD.craft_name_snapshot
       OR NEW.plan_category IS DISTINCT FROM OLD.plan_category THEN
        SELECT craft_type, name, plan_category INTO source_type, source_name, source_category
        FROM workshop_config_craft WHERE id = NEW.craft_id FOR KEY SHARE;
        IF source_type IS NULL
           OR NEW.craft_type_snapshot <> source_type
           OR NEW.craft_name_snapshot <> source_name
           OR NEW.plan_category IS DISTINCT FROM source_category THEN
            RAISE EXCEPTION 'schedule craft snapshot does not match its source craft' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NEW.removed_at IS NULL AND parent_removed_at IS NOT NULL THEN
        RAISE EXCEPTION 'active craft cannot belong to a removed schedule product' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION ps_protect_referenced_craft() RETURNS trigger AS $$
BEGIN
    IF (NEW.craft_type IS DISTINCT FROM OLD.craft_type
        OR NEW.plan_category IS DISTINCT FROM OLD.plan_category)
       AND EXISTS (
           SELECT 1 FROM production_schedule_product_craft WHERE craft_id = OLD.id
       ) THEN
        RAISE EXCEPTION 'referenced craft type or plan category cannot be changed' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ps_referenced_craft_guard
BEFORE UPDATE OF craft_type, plan_category ON workshop_config_craft
FOR EACH ROW EXECUTE FUNCTION ps_protect_referenced_craft();

CREATE OR REPLACE FUNCTION ps_protect_source_product() RETURNS trigger AS $$
DECLARE
    has_schedule_history boolean;
    maximum_planned bigint;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM production_schedule_product sp WHERE sp.product_line_id = OLD.id
    ) INTO has_schedule_history;
    SELECT max(sp.planned_quantity) INTO maximum_planned
    FROM production_schedule_product sp
    JOIN production_schedule s ON s.id = sp.schedule_id
    WHERE sp.product_line_id = OLD.id
      AND sp.removed_at IS NULL
      AND s.record_status = 'ACTIVE';
    IF TG_OP = 'DELETE' THEN
        IF has_schedule_history THEN
            RAISE EXCEPTION 'scheduled production task product cannot be deleted' USING ERRCODE = '23514';
        END IF;
        RETURN OLD;
    END IF;
    IF has_schedule_history
       AND (NEW.production_task_id <> OLD.production_task_id
            OR NEW.product_id <> OLD.product_id
            OR NEW.unit_id <> OLD.unit_id) THEN
        RAISE EXCEPTION 'scheduled production task product identity cannot be changed' USING ERRCODE = '23514';
    END IF;
    IF maximum_planned IS NOT NULL AND NEW.quantity < maximum_planned THEN
        RAISE EXCEPTION 'production task quantity cannot be lower than active planned quantity' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS ps_referenced_craft_guard ON workshop_config_craft;
DROP TRIGGER IF EXISTS ps_schedule_craft_touch_parent ON production_schedule_product_craft;
DROP TRIGGER IF EXISTS ps_schedule_product_touch_parent ON production_schedule_product;
DROP FUNCTION IF EXISTS ps_protect_referenced_craft();
DROP FUNCTION IF EXISTS ps_touch_parent_schedule();

CREATE OR REPLACE FUNCTION ps_validate_schedule_craft_row() RETURNS trigger AS $$
DECLARE
    parent_removed_at timestamptz;
    source_type varchar(20);
    source_name varchar(100);
    source_category varchar(20);
BEGIN
    SELECT removed_at INTO parent_removed_at
    FROM production_schedule_product WHERE id = NEW.schedule_product_id FOR KEY SHARE;
    SELECT craft_type, name, plan_category INTO source_type, source_name, source_category
    FROM workshop_config_craft WHERE id = NEW.craft_id FOR KEY SHARE;
    IF source_type IS NULL
       OR NEW.craft_type_snapshot <> source_type
       OR NEW.craft_name_snapshot <> source_name
       OR NEW.plan_category IS DISTINCT FROM source_category THEN
        RAISE EXCEPTION 'schedule craft snapshot does not match its source craft' USING ERRCODE = '23514';
    END IF;
    IF NEW.removed_at IS NULL AND parent_removed_at IS NOT NULL THEN
        RAISE EXCEPTION 'active craft cannot belong to a removed schedule product' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION ps_protect_source_product() RETURNS trigger AS $$
DECLARE
    maximum_planned bigint;
BEGIN
    SELECT max(sp.planned_quantity) INTO maximum_planned
    FROM production_schedule_product sp
    JOIN production_schedule s ON s.id = sp.schedule_id
    WHERE sp.product_line_id = OLD.id AND sp.removed_at IS NULL AND s.record_status = 'ACTIVE';
    IF maximum_planned IS NULL THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'scheduled production task product cannot be deleted' USING ERRCODE = '23514';
    END IF;
    IF NEW.production_task_id <> OLD.production_task_id OR NEW.product_id <> OLD.product_id OR NEW.unit_id <> OLD.unit_id THEN
        RAISE EXCEPTION 'scheduled production task product identity cannot be changed' USING ERRCODE = '23514';
    END IF;
    IF NEW.quantity < maximum_planned THEN
        RAISE EXCEPTION 'production task quantity cannot be lower than active planned quantity' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


class Migration(migrations.Migration):
    dependencies = [("production_scheduling", "0003_integrity_triggers")]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
