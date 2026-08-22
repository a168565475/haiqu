from django.db import migrations


FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION haiqu_block_row_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only; % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;

CREATE TRIGGER audit_log_append_only
BEFORE UPDATE OR DELETE ON audit_log
FOR EACH ROW EXECUTE FUNCTION haiqu_block_row_change();

CREATE OR REPLACE FUNCTION haiqu_check_organization_parent()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.parent_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF EXISTS (
        WITH RECURSIVE ancestors AS (
            SELECT id, parent_id
            FROM organization_unit
            WHERE id = NEW.parent_id
            UNION ALL
            SELECT parent.id, parent.parent_id
            FROM organization_unit parent
            JOIN ancestors child ON parent.id = child.parent_id
        )
        SELECT 1 FROM ancestors WHERE id = NEW.id
    ) THEN
        RAISE EXCEPTION 'organization hierarchy cannot contain a cycle'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER organization_parent_cycle_guard
BEFORE INSERT OR UPDATE OF parent_id ON organization_unit
FOR EACH ROW EXECUTE FUNCTION haiqu_check_organization_parent();

CREATE OR REPLACE FUNCTION haiqu_check_customer_contact()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.transaction_entity_id IS NOT NULL
       AND NOT EXISTS (
           SELECT 1
           FROM customer_transaction_entity entity
           WHERE entity.id = NEW.transaction_entity_id
             AND entity.customer_account_id = NEW.customer_account_id
       ) THEN
        RAISE EXCEPTION 'contact transaction entity must belong to the same customer account'
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    IF NEW.source_contact_id IS NOT NULL
       AND NOT EXISTS (
           SELECT 1
           FROM customer_contact source
           WHERE source.id = NEW.source_contact_id
             AND source.customer_account_id = NEW.customer_account_id
       ) THEN
        RAISE EXCEPTION 'source contact must belong to the same customer account'
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    IF NEW.source_contact_id IS NOT NULL AND EXISTS (
        WITH RECURSIVE lineage AS (
            SELECT id, source_contact_id
            FROM customer_contact
            WHERE id = NEW.source_contact_id
            UNION ALL
            SELECT contact.id, contact.source_contact_id
            FROM customer_contact contact
            JOIN lineage child ON contact.id = child.source_contact_id
        )
        SELECT 1 FROM lineage WHERE id = NEW.id
    ) THEN
        RAISE EXCEPTION 'contact lineage cannot contain a cycle'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER customer_contact_consistency_guard
BEFORE INSERT OR UPDATE OF customer_account_id, transaction_entity_id, source_contact_id
ON customer_contact
FOR EACH ROW EXECUTE FUNCTION haiqu_check_customer_contact();

CREATE OR REPLACE FUNCTION haiqu_check_inquiry()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.transaction_entity_id IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM customer_transaction_entity entity
           WHERE entity.id = NEW.transaction_entity_id
             AND entity.customer_account_id = NEW.customer_account_id
       ) THEN
        RAISE EXCEPTION 'inquiry transaction entity must belong to the same customer account'
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    IF NEW.customer_contact_id IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM customer_contact contact
           WHERE contact.id = NEW.customer_contact_id
             AND contact.customer_account_id = NEW.customer_account_id
       ) THEN
        RAISE EXCEPTION 'inquiry contact must belong to the same customer account'
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    IF NEW.status IN ('SUBMITTED', 'IN_PROGRESS', 'QUOTED', 'CLOSED')
       AND NOT EXISTS (SELECT 1 FROM inquiry_item item WHERE item.inquiry_id = NEW.id) THEN
        RAISE EXCEPTION 'a submitted inquiry must contain at least one item'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER inquiry_consistency_guard
BEFORE INSERT OR UPDATE OF customer_account_id, transaction_entity_id, customer_contact_id, status
ON inquiry
FOR EACH ROW EXECUTE FUNCTION haiqu_check_inquiry();

CREATE OR REPLACE FUNCTION haiqu_check_inquiry_has_item()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM inquiry parent
        WHERE parent.id = OLD.inquiry_id
          AND parent.status IN ('SUBMITTED', 'IN_PROGRESS', 'QUOTED', 'CLOSED')
    ) AND NOT EXISTS (
        SELECT 1 FROM inquiry_item item WHERE item.inquiry_id = OLD.inquiry_id
    ) THEN
        RAISE EXCEPTION 'a submitted inquiry must contain at least one item'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER inquiry_item_cardinality_guard
AFTER DELETE ON inquiry_item
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION haiqu_check_inquiry_has_item();

CREATE OR REPLACE FUNCTION haiqu_check_quotation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM customer_transaction_entity entity
        WHERE entity.id = NEW.transaction_entity_id
          AND entity.customer_account_id = NEW.customer_account_id
    ) THEN
        RAISE EXCEPTION 'quotation transaction entity must belong to the same customer account'
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    IF NEW.source_inquiry_id IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM inquiry source
           WHERE source.id = NEW.source_inquiry_id
             AND source.customer_account_id = NEW.customer_account_id
       ) THEN
        RAISE EXCEPTION 'quotation source inquiry must belong to the same customer account'
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    IF NEW.accepted_version_id IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM quotation_version version
           WHERE version.id = NEW.accepted_version_id
             AND version.quotation_id = NEW.id
       ) THEN
        RAISE EXCEPTION 'accepted version must belong to the quotation'
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    IF NEW.outcome_status = 'WON' AND NEW.accepted_version_id IS NULL THEN
        RAISE EXCEPTION 'a won quotation must specify its accepted version'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER quotation_consistency_guard
BEFORE INSERT OR UPDATE OF customer_account_id, transaction_entity_id, source_inquiry_id,
    accepted_version_id, outcome_status
ON quotation
FOR EACH ROW EXECUTE FUNCTION haiqu_check_quotation();

CREATE OR REPLACE FUNCTION haiqu_guard_quotation_version()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.status <> 'DRAFT' THEN
        IF NEW.status = 'DRAFT' THEN
            RAISE EXCEPTION 'a locked quotation version cannot return to draft'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;

        IF ROW(
            NEW.quotation_id,
            NEW.quotation_template_id,
            NEW.version_number,
            NEW.currency_code,
            NEW.language_code,
            NEW.subtotal_amount,
            NEW.discount_amount,
            NEW.tax_amount,
            NEW.total_amount,
            NEW.valid_until,
            NEW.locked_at,
            NEW.locked_by_employee_id,
            NEW.transaction_entity_snapshot,
            NEW.address_snapshot,
            NEW.contact_snapshot,
            NEW.template_snapshot,
            NEW.terms_snapshot,
            NEW.notes
        ) IS DISTINCT FROM ROW(
            OLD.quotation_id,
            OLD.quotation_template_id,
            OLD.version_number,
            OLD.currency_code,
            OLD.language_code,
            OLD.subtotal_amount,
            OLD.discount_amount,
            OLD.tax_amount,
            OLD.total_amount,
            OLD.valid_until,
            OLD.locked_at,
            OLD.locked_by_employee_id,
            OLD.transaction_entity_snapshot,
            OLD.address_snapshot,
            OLD.contact_snapshot,
            OLD.template_snapshot,
            OLD.terms_snapshot,
            OLD.notes
        ) THEN
            RAISE EXCEPTION 'locked quotation snapshot and commercial terms are immutable'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;

    IF NEW.status IN ('ISSUED', 'SENT') THEN
        IF NEW.transaction_entity_snapshot IS NULL OR NEW.transaction_entity_snapshot = '{}'::jsonb
           OR NEW.address_snapshot IS NULL OR NEW.address_snapshot = '{}'::jsonb
           OR NEW.contact_snapshot IS NULL OR NEW.contact_snapshot = '{}'::jsonb THEN
            RAISE EXCEPTION 'an issued quotation version requires entity, address and contact snapshots'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;

        IF NOT EXISTS (
            SELECT 1 FROM quotation_line line WHERE line.quotation_version_id = NEW.id
        ) THEN
            RAISE EXCEPTION 'an issued quotation version must contain at least one line'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER quotation_version_snapshot_guard
BEFORE INSERT OR UPDATE ON quotation_version
FOR EACH ROW EXECUTE FUNCTION haiqu_guard_quotation_version();

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

CREATE TRIGGER quotation_line_lock_guard
BEFORE INSERT OR UPDATE OR DELETE ON quotation_line
FOR EACH ROW EXECUTE FUNCTION haiqu_guard_quotation_line();

CREATE OR REPLACE FUNCTION haiqu_guard_quotation_tier()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    parent_status varchar;
    target_line_id uuid;
BEGIN
    target_line_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.quotation_line_id ELSE NEW.quotation_line_id END;

    SELECT version.status INTO parent_status
    FROM quotation_line line
    JOIN quotation_version version ON version.id = line.quotation_version_id
    WHERE line.id = target_line_id;

    IF parent_status <> 'DRAFT' THEN
        RAISE EXCEPTION 'quantity tiers of a locked quotation version are immutable'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER quotation_tier_lock_guard
BEFORE INSERT OR UPDATE OR DELETE ON quotation_quantity_tier
FOR EACH ROW EXECUTE FUNCTION haiqu_guard_quotation_tier();

CREATE OR REPLACE FUNCTION haiqu_check_sample_request()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.transaction_entity_id IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM customer_transaction_entity entity
           WHERE entity.id = NEW.transaction_entity_id
             AND entity.customer_account_id = NEW.customer_account_id
       ) THEN
        RAISE EXCEPTION 'sample transaction entity must belong to the same customer account'
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    IF NEW.customer_contact_id IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM customer_contact contact
           WHERE contact.id = NEW.customer_contact_id
             AND contact.customer_account_id = NEW.customer_account_id
       ) THEN
        RAISE EXCEPTION 'sample contact must belong to the same customer account'
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    IF NEW.source_inquiry_id IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM inquiry source
           WHERE source.id = NEW.source_inquiry_id
             AND source.customer_account_id = NEW.customer_account_id
       ) THEN
        RAISE EXCEPTION 'sample source inquiry must belong to the same customer account'
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    IF NEW.source_quotation_version_id IS NOT NULL
       AND NOT EXISTS (
           SELECT 1
           FROM quotation_version version
           JOIN quotation quote ON quote.id = version.quotation_id
           WHERE version.id = NEW.source_quotation_version_id
             AND quote.customer_account_id = NEW.customer_account_id
       ) THEN
        RAISE EXCEPTION 'sample source quotation must belong to the same customer account'
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    IF NEW.status IN ('PENDING', 'PREPARING', 'SHIPPED', 'FEEDBACK_PENDING', 'COMPLETED')
       AND NOT EXISTS (SELECT 1 FROM sample_item item WHERE item.sample_request_id = NEW.id) THEN
        RAISE EXCEPTION 'an active sample request must contain at least one item'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER sample_request_consistency_guard
BEFORE INSERT OR UPDATE OF customer_account_id, transaction_entity_id, customer_contact_id,
    source_inquiry_id, source_quotation_version_id, status
ON sample_request
FOR EACH ROW EXECUTE FUNCTION haiqu_check_sample_request();

CREATE OR REPLACE FUNCTION haiqu_check_sample_has_item()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM sample_request parent
        WHERE parent.id = OLD.sample_request_id
          AND parent.status IN ('PENDING', 'PREPARING', 'SHIPPED', 'FEEDBACK_PENDING', 'COMPLETED')
    ) AND NOT EXISTS (
        SELECT 1 FROM sample_item item WHERE item.sample_request_id = OLD.sample_request_id
    ) THEN
        RAISE EXCEPTION 'an active sample request must contain at least one item'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER sample_item_cardinality_guard
AFTER DELETE ON sample_item
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION haiqu_check_sample_has_item();

CREATE OR REPLACE FUNCTION haiqu_check_sample_shipment()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.status IN ('SHIPPED', 'DELIVERED')
       AND ROW(
           NEW.sample_request_id,
           NEW.carrier_code,
           NEW.tracking_number,
           NEW.recipient_snapshot,
           NEW.address_snapshot,
           NEW.shipped_at
       ) IS DISTINCT FROM ROW(
           OLD.sample_request_id,
           OLD.carrier_code,
           OLD.tracking_number,
           OLD.recipient_snapshot,
           OLD.address_snapshot,
           OLD.shipped_at
       ) THEN
        RAISE EXCEPTION 'shipped sample logistics snapshot is immutable'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    IF NEW.status IN ('SHIPPED', 'DELIVERED') THEN
        IF NEW.shipped_at IS NULL
           OR NEW.recipient_snapshot IS NULL OR NEW.recipient_snapshot = '{}'::jsonb
           OR NEW.address_snapshot IS NULL OR NEW.address_snapshot = '{}'::jsonb THEN
            RAISE EXCEPTION 'a shipped sample requires shipment time, recipient and address snapshots'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;

        IF EXISTS (
            SELECT 1
            FROM sample_fee_record fee
            WHERE fee.sample_request_id = NEW.sample_request_id
              AND fee.superseded_at IS NULL
              AND fee.fee_decision = 'PAID'
              AND fee.verification_status NOT IN ('MANUALLY_CONFIRMED')
        ) AND NOT NEW.fee_warning_acknowledged THEN
            RAISE EXCEPTION 'unverified paid sample fee requires an explicit warning acknowledgement before shipment'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER sample_shipment_consistency_guard
BEFORE INSERT OR UPDATE ON sample_shipment
FOR EACH ROW EXECUTE FUNCTION haiqu_check_sample_shipment();

CREATE OR REPLACE FUNCTION haiqu_check_sample_shipment_item()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    shipment_request_id uuid;
    item_request_id uuid;
    shipment_status varchar;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT status INTO shipment_status
        FROM sample_shipment WHERE id = OLD.sample_shipment_id;
        IF shipment_status IN ('SHIPPED', 'DELIVERED') THEN
            RAISE EXCEPTION 'items of a shipped sample shipment are immutable'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;

    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        SELECT sample_request_id, status
        INTO shipment_request_id, shipment_status
        FROM sample_shipment WHERE id = NEW.sample_shipment_id;

        SELECT sample_request_id INTO item_request_id
        FROM sample_item WHERE id = NEW.sample_item_id;

        IF shipment_request_id IS DISTINCT FROM item_request_id THEN
            RAISE EXCEPTION 'shipment item must belong to the same sample request'
                USING ERRCODE = 'foreign_key_violation';
        END IF;

        IF shipment_status IN ('SHIPPED', 'DELIVERED') THEN
            RAISE EXCEPTION 'items cannot be added to a shipped sample shipment'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN NEW;
    END IF;

    RETURN OLD;
END;
$$;

CREATE TRIGGER sample_shipment_item_consistency_guard
BEFORE INSERT OR UPDATE OR DELETE ON sample_shipment_item
FOR EACH ROW EXECUTE FUNCTION haiqu_check_sample_shipment_item();

CREATE OR REPLACE FUNCTION haiqu_check_customer_merge_completion()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    survivor_count integer;
    source_count integer;
BEGIN
    IF NEW.status = 'COMPLETED' AND (TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM 'COMPLETED') THEN
        SELECT
            count(*) FILTER (WHERE member_role = 'SURVIVOR'),
            count(*) FILTER (WHERE member_role = 'SOURCE')
        INTO survivor_count, source_count
        FROM customer_merge_member
        WHERE merge_operation_id = NEW.id;

        IF survivor_count <> 1 OR source_count < 1 THEN
            RAISE EXCEPTION 'a completed merge requires exactly one survivor and at least one source customer'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;

        IF NEW.executed_at IS NULL THEN
            RAISE EXCEPTION 'a completed merge requires executed_at'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER customer_merge_completion_guard
BEFORE INSERT OR UPDATE OF status, executed_at ON customer_merge_operation
FOR EACH ROW EXECUTE FUNCTION haiqu_check_customer_merge_completion();

CREATE OR REPLACE FUNCTION haiqu_guard_customer_merge_member()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    target_operation_id uuid;
BEGIN
    target_operation_id := CASE WHEN TG_OP = 'INSERT' THEN NEW.merge_operation_id ELSE OLD.merge_operation_id END;

    IF EXISTS (
        SELECT 1 FROM customer_merge_operation operation
        WHERE operation.id = target_operation_id AND operation.status = 'COMPLETED'
    ) THEN
        RAISE EXCEPTION 'members of a completed customer merge are immutable'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER customer_merge_member_guard
BEFORE INSERT OR UPDATE OR DELETE ON customer_merge_member
FOR EACH ROW EXECUTE FUNCTION haiqu_guard_customer_merge_member();

CREATE OR REPLACE FUNCTION haiqu_check_communication_link()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_TABLE_NAME = 'communication_contact_participant' AND NOT EXISTS (
        SELECT 1
        FROM customer_communication communication
        JOIN customer_contact contact ON contact.id = NEW.customer_contact_id
        WHERE communication.id = NEW.communication_id
          AND communication.customer_account_id = contact.customer_account_id
    ) THEN
        RAISE EXCEPTION 'communication contact must belong to the same customer account'
            USING ERRCODE = 'foreign_key_violation';
    ELSIF TG_TABLE_NAME = 'communication_inquiry_link' AND NOT EXISTS (
        SELECT 1
        FROM customer_communication communication
        JOIN inquiry linked ON linked.id = NEW.inquiry_id
        WHERE communication.id = NEW.communication_id
          AND communication.customer_account_id = linked.customer_account_id
    ) THEN
        RAISE EXCEPTION 'linked inquiry must belong to the same customer account'
            USING ERRCODE = 'foreign_key_violation';
    ELSIF TG_TABLE_NAME = 'communication_quotation_version_link' AND NOT EXISTS (
        SELECT 1
        FROM customer_communication communication
        JOIN quotation_version version ON version.id = NEW.quotation_version_id
        JOIN quotation quote ON quote.id = version.quotation_id
        WHERE communication.id = NEW.communication_id
          AND communication.customer_account_id = quote.customer_account_id
    ) THEN
        RAISE EXCEPTION 'linked quotation must belong to the same customer account'
            USING ERRCODE = 'foreign_key_violation';
    ELSIF TG_TABLE_NAME = 'communication_sample_request_link' AND NOT EXISTS (
        SELECT 1
        FROM customer_communication communication
        JOIN sample_request sample ON sample.id = NEW.sample_request_id
        WHERE communication.id = NEW.communication_id
          AND communication.customer_account_id = sample.customer_account_id
    ) THEN
        RAISE EXCEPTION 'linked sample request must belong to the same customer account'
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER communication_contact_consistency_guard
BEFORE INSERT OR UPDATE ON communication_contact_participant
FOR EACH ROW EXECUTE FUNCTION haiqu_check_communication_link();

CREATE TRIGGER communication_inquiry_consistency_guard
BEFORE INSERT OR UPDATE ON communication_inquiry_link
FOR EACH ROW EXECUTE FUNCTION haiqu_check_communication_link();

CREATE TRIGGER communication_quote_consistency_guard
BEFORE INSERT OR UPDATE ON communication_quotation_version_link
FOR EACH ROW EXECUTE FUNCTION haiqu_check_communication_link();

CREATE TRIGGER communication_sample_consistency_guard
BEFORE INSERT OR UPDATE ON communication_sample_request_link
FOR EACH ROW EXECUTE FUNCTION haiqu_check_communication_link();
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS communication_sample_consistency_guard ON communication_sample_request_link;
DROP TRIGGER IF EXISTS communication_quote_consistency_guard ON communication_quotation_version_link;
DROP TRIGGER IF EXISTS communication_inquiry_consistency_guard ON communication_inquiry_link;
DROP TRIGGER IF EXISTS communication_contact_consistency_guard ON communication_contact_participant;
DROP FUNCTION IF EXISTS haiqu_check_communication_link();

DROP TRIGGER IF EXISTS customer_merge_member_guard ON customer_merge_member;
DROP FUNCTION IF EXISTS haiqu_guard_customer_merge_member();
DROP TRIGGER IF EXISTS customer_merge_completion_guard ON customer_merge_operation;
DROP FUNCTION IF EXISTS haiqu_check_customer_merge_completion();

DROP TRIGGER IF EXISTS sample_shipment_item_consistency_guard ON sample_shipment_item;
DROP FUNCTION IF EXISTS haiqu_check_sample_shipment_item();
DROP TRIGGER IF EXISTS sample_shipment_consistency_guard ON sample_shipment;
DROP FUNCTION IF EXISTS haiqu_check_sample_shipment();
DROP TRIGGER IF EXISTS sample_item_cardinality_guard ON sample_item;
DROP FUNCTION IF EXISTS haiqu_check_sample_has_item();
DROP TRIGGER IF EXISTS sample_request_consistency_guard ON sample_request;
DROP FUNCTION IF EXISTS haiqu_check_sample_request();

DROP TRIGGER IF EXISTS quotation_tier_lock_guard ON quotation_quantity_tier;
DROP FUNCTION IF EXISTS haiqu_guard_quotation_tier();
DROP TRIGGER IF EXISTS quotation_line_lock_guard ON quotation_line;
DROP FUNCTION IF EXISTS haiqu_guard_quotation_line();
DROP TRIGGER IF EXISTS quotation_version_snapshot_guard ON quotation_version;
DROP FUNCTION IF EXISTS haiqu_guard_quotation_version();
DROP TRIGGER IF EXISTS quotation_consistency_guard ON quotation;
DROP FUNCTION IF EXISTS haiqu_check_quotation();

DROP TRIGGER IF EXISTS inquiry_item_cardinality_guard ON inquiry_item;
DROP FUNCTION IF EXISTS haiqu_check_inquiry_has_item();
DROP TRIGGER IF EXISTS inquiry_consistency_guard ON inquiry;
DROP FUNCTION IF EXISTS haiqu_check_inquiry();

DROP TRIGGER IF EXISTS customer_contact_consistency_guard ON customer_contact;
DROP FUNCTION IF EXISTS haiqu_check_customer_contact();
DROP TRIGGER IF EXISTS organization_parent_cycle_guard ON organization_unit;
DROP FUNCTION IF EXISTS haiqu_check_organization_parent();
DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log;
DROP FUNCTION IF EXISTS haiqu_block_row_change();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_postgresql_extensions"),
        ("organizations", "0001_initial"),
        ("audit", "0002_initial"),
        ("customers", "0001_initial"),
        ("inquiries", "0002_initial"),
        ("quotations", "0001_initial"),
        ("samples", "0001_initial"),
        ("crm", "0003_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
