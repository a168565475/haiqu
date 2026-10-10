from django.db import migrations


FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION ps_block_physical_delete() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'production scheduling history cannot be physically deleted' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ps_schedule_no_delete BEFORE DELETE ON production_schedule
FOR EACH ROW EXECUTE FUNCTION ps_block_physical_delete();
CREATE TRIGGER ps_schedule_product_no_delete BEFORE DELETE ON production_schedule_product
FOR EACH ROW EXECUTE FUNCTION ps_block_physical_delete();
CREATE TRIGGER ps_schedule_craft_no_delete BEFORE DELETE ON production_schedule_product_craft
FOR EACH ROW EXECUTE FUNCTION ps_block_physical_delete();

CREATE OR REPLACE FUNCTION ps_validate_schedule_row() RETURNS trigger AS $$
DECLARE
    task_status varchar(30);
    task_archived_at timestamptz;
BEGIN
    IF NEW.record_status = 'ACTIVE' THEN
        SELECT status, archived_at INTO task_status, task_archived_at
        FROM production_task WHERE id = NEW.production_task_id FOR KEY SHARE;
        IF NOT FOUND OR task_status <> 'READY' OR task_archived_at IS NOT NULL THEN
            RAISE EXCEPTION 'active schedule requires a READY and unarchived production task' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ps_schedule_row_guard
BEFORE INSERT OR UPDATE OF production_task_id, record_status ON production_schedule
FOR EACH ROW EXECUTE FUNCTION ps_validate_schedule_row();

CREATE OR REPLACE FUNCTION ps_validate_schedule_product_row() RETURNS trigger AS $$
DECLARE
    schedule_task_id uuid;
    schedule_status varchar(20);
    source_task_id uuid;
    source_quantity bigint;
    source_unit_id uuid;
BEGIN
    SELECT production_task_id, record_status INTO schedule_task_id, schedule_status
    FROM production_schedule WHERE id = NEW.schedule_id FOR KEY SHARE;
    SELECT production_task_id, quantity, unit_id INTO source_task_id, source_quantity, source_unit_id
    FROM production_task_product WHERE id = NEW.product_line_id FOR KEY SHARE;
    IF schedule_task_id IS NULL OR source_task_id IS NULL OR schedule_task_id <> source_task_id THEN
        RAISE EXCEPTION 'schedule product must belong to the schedule production task' USING ERRCODE = '23514';
    END IF;
    IF NEW.source_quantity_snapshot <> source_quantity OR NEW.unit_id <> source_unit_id THEN
        RAISE EXCEPTION 'schedule product source quantity or unit snapshot is invalid' USING ERRCODE = '23514';
    END IF;
    IF NEW.removed_at IS NULL AND schedule_status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'active schedule product requires an active schedule' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ps_schedule_product_row_guard
BEFORE INSERT OR UPDATE OF schedule_id, product_line_id, source_quantity_snapshot, unit_id, planned_quantity
ON production_schedule_product FOR EACH ROW EXECUTE FUNCTION ps_validate_schedule_product_row();

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

CREATE TRIGGER ps_schedule_craft_row_guard
BEFORE INSERT OR UPDATE OF schedule_product_id, craft_id, craft_type_snapshot, craft_name_snapshot, plan_category, removed_at
ON production_schedule_product_craft FOR EACH ROW EXECUTE FUNCTION ps_validate_schedule_craft_row();

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

CREATE TRIGGER ps_source_product_guard
BEFORE UPDATE OF production_task_id, product_id, unit_id, quantity OR DELETE ON production_task_product
FOR EACH ROW EXECUTE FUNCTION ps_protect_source_product();

CREATE OR REPLACE FUNCTION ps_assert_schedule_integrity(target_schedule_id uuid) RETURNS void AS $$
BEGIN
    IF target_schedule_id IS NULL THEN RETURN; END IF;
    IF EXISTS (
        SELECT 1 FROM production_schedule s
        WHERE s.id = target_schedule_id AND s.record_status = 'ACTIVE'
          AND NOT EXISTS (
              SELECT 1 FROM production_schedule_product sp
              WHERE sp.schedule_id = s.id AND sp.removed_at IS NULL
          )
    ) THEN
        RAISE EXCEPTION 'active schedule requires at least one active product' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM production_schedule_product sp
        JOIN production_schedule s ON s.id = sp.schedule_id
        JOIN production_task_product source ON source.id = sp.product_line_id
        WHERE sp.schedule_id = target_schedule_id AND sp.removed_at IS NULL
          AND s.production_task_id <> source.production_task_id
    ) THEN
        RAISE EXCEPTION 'active schedule product has an invalid parent or source task' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM production_schedule_product sp
        JOIN production_schedule s ON s.id = sp.schedule_id
        WHERE sp.schedule_id = target_schedule_id AND sp.removed_at IS NULL AND s.record_status = 'ACTIVE'
          AND NOT EXISTS (
              SELECT 1 FROM production_schedule_product_craft sc
              WHERE sc.schedule_product_id = sp.id AND sc.removed_at IS NULL
          )
    ) THEN
        RAISE EXCEPTION 'every active schedule product requires at least one active craft' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM production_schedule_product_craft sc
        JOIN production_schedule_product sp ON sp.id = sc.schedule_product_id
        WHERE sp.schedule_id = target_schedule_id AND sc.removed_at IS NULL AND sp.removed_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'active craft cannot belong to a removed schedule product' USING ERRCODE = '23514';
    END IF;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION ps_deferred_integrity_guard() RETURNS trigger AS $$
DECLARE
    old_schedule_id uuid;
    new_schedule_id uuid;
BEGIN
    IF TG_TABLE_NAME = 'production_schedule' THEN
        IF TG_OP <> 'INSERT' THEN old_schedule_id := OLD.id; END IF;
        IF TG_OP <> 'DELETE' THEN new_schedule_id := NEW.id; END IF;
    ELSIF TG_TABLE_NAME = 'production_schedule_product' THEN
        IF TG_OP <> 'INSERT' THEN old_schedule_id := OLD.schedule_id; END IF;
        IF TG_OP <> 'DELETE' THEN new_schedule_id := NEW.schedule_id; END IF;
    ELSE
        IF TG_OP <> 'INSERT' THEN
            SELECT schedule_id INTO old_schedule_id FROM production_schedule_product WHERE id = OLD.schedule_product_id;
        END IF;
        IF TG_OP <> 'DELETE' THEN
            SELECT schedule_id INTO new_schedule_id FROM production_schedule_product WHERE id = NEW.schedule_product_id;
        END IF;
    END IF;
    PERFORM ps_assert_schedule_integrity(old_schedule_id);
    IF new_schedule_id IS DISTINCT FROM old_schedule_id THEN
        PERFORM ps_assert_schedule_integrity(new_schedule_id);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER ps_schedule_integrity_deferred
AFTER INSERT OR UPDATE OR DELETE ON production_schedule
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ps_deferred_integrity_guard();
CREATE CONSTRAINT TRIGGER ps_schedule_product_integrity_deferred
AFTER INSERT OR UPDATE OR DELETE ON production_schedule_product
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ps_deferred_integrity_guard();
CREATE CONSTRAINT TRIGGER ps_schedule_craft_integrity_deferred
AFTER INSERT OR UPDATE OR DELETE ON production_schedule_product_craft
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ps_deferred_integrity_guard();
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS ps_schedule_craft_integrity_deferred ON production_schedule_product_craft;
DROP TRIGGER IF EXISTS ps_schedule_product_integrity_deferred ON production_schedule_product;
DROP TRIGGER IF EXISTS ps_schedule_integrity_deferred ON production_schedule;
DROP TRIGGER IF EXISTS ps_source_product_guard ON production_task_product;
DROP TRIGGER IF EXISTS ps_schedule_craft_row_guard ON production_schedule_product_craft;
DROP TRIGGER IF EXISTS ps_schedule_product_row_guard ON production_schedule_product;
DROP TRIGGER IF EXISTS ps_schedule_row_guard ON production_schedule;
DROP TRIGGER IF EXISTS ps_schedule_craft_no_delete ON production_schedule_product_craft;
DROP TRIGGER IF EXISTS ps_schedule_product_no_delete ON production_schedule_product;
DROP TRIGGER IF EXISTS ps_schedule_no_delete ON production_schedule;
DROP FUNCTION IF EXISTS ps_deferred_integrity_guard();
DROP FUNCTION IF EXISTS ps_assert_schedule_integrity(uuid);
DROP FUNCTION IF EXISTS ps_protect_source_product();
DROP FUNCTION IF EXISTS ps_validate_schedule_craft_row();
DROP FUNCTION IF EXISTS ps_validate_schedule_product_row();
DROP FUNCTION IF EXISTS ps_validate_schedule_row();
DROP FUNCTION IF EXISTS ps_block_physical_delete();
"""


class Migration(migrations.Migration):
    dependencies = [("production_scheduling", "0002_schedule_number_rule")]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
