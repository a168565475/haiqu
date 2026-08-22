from django.db import migrations


FIX_SQL = r"""
CREATE OR REPLACE FUNCTION haiqu_check_communication_link()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_TABLE_NAME = 'communication_contact_participant' THEN
        IF NOT EXISTS (
            SELECT 1
            FROM customer_communication communication
            JOIN customer_contact contact ON contact.id = NEW.customer_contact_id
            WHERE communication.id = NEW.communication_id
              AND communication.customer_account_id = contact.customer_account_id
        ) THEN
            RAISE EXCEPTION 'communication contact must belong to the same customer account'
                USING ERRCODE = 'foreign_key_violation';
        END IF;
    ELSIF TG_TABLE_NAME = 'communication_inquiry_link' THEN
        IF NOT EXISTS (
            SELECT 1
            FROM customer_communication communication
            JOIN inquiry linked ON linked.id = NEW.inquiry_id
            WHERE communication.id = NEW.communication_id
              AND communication.customer_account_id = linked.customer_account_id
        ) THEN
            RAISE EXCEPTION 'linked inquiry must belong to the same customer account'
                USING ERRCODE = 'foreign_key_violation';
        END IF;
    ELSIF TG_TABLE_NAME = 'communication_quotation_version_link' THEN
        IF NOT EXISTS (
            SELECT 1
            FROM customer_communication communication
            JOIN quotation_version version ON version.id = NEW.quotation_version_id
            JOIN quotation quote ON quote.id = version.quotation_id
            WHERE communication.id = NEW.communication_id
              AND communication.customer_account_id = quote.customer_account_id
        ) THEN
            RAISE EXCEPTION 'linked quotation must belong to the same customer account'
                USING ERRCODE = 'foreign_key_violation';
        END IF;
    ELSIF TG_TABLE_NAME = 'communication_sample_request_link' THEN
        IF NOT EXISTS (
            SELECT 1
            FROM customer_communication communication
            JOIN sample_request sample ON sample.id = NEW.sample_request_id
            WHERE communication.id = NEW.communication_id
              AND communication.customer_account_id = sample.customer_account_id
        ) THEN
            RAISE EXCEPTION 'linked sample request must belong to the same customer account'
                USING ERRCODE = 'foreign_key_violation';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;
"""


REVERSE_SQL = r"""
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
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0003_business_number_sequences")]

    operations = [migrations.RunSQL(FIX_SQL, reverse_sql=REVERSE_SQL)]
