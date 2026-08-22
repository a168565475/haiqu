--
-- PostgreSQL database dump
--

\restrict BAqEVkDBc9MKXpLGwxOla8WTC3UbEYIHA6jsvHVCK9XCQ8T5H8wugpCBWU4H5gQ

-- Dumped from database version 17.11
-- Dumped by pg_dump version 17.11

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: btree_gist; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public;


--
-- Name: EXTENSION btree_gist; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION btree_gist IS 'support for indexing common datatypes in GiST';


--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


--
-- Name: haiqu_block_row_change(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haiqu_block_row_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    RAISE EXCEPTION '% is append-only; % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;


--
-- Name: haiqu_check_communication_link(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haiqu_check_communication_link() RETURNS trigger
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


--
-- Name: haiqu_check_customer_contact(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haiqu_check_customer_contact() RETURNS trigger
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


--
-- Name: haiqu_check_customer_merge_completion(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haiqu_check_customer_merge_completion() RETURNS trigger
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


--
-- Name: haiqu_check_inquiry(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haiqu_check_inquiry() RETURNS trigger
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


--
-- Name: haiqu_check_inquiry_has_item(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haiqu_check_inquiry_has_item() RETURNS trigger
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


--
-- Name: haiqu_check_organization_parent(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haiqu_check_organization_parent() RETURNS trigger
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


--
-- Name: haiqu_check_quotation(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haiqu_check_quotation() RETURNS trigger
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


--
-- Name: haiqu_check_sample_has_item(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haiqu_check_sample_has_item() RETURNS trigger
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


--
-- Name: haiqu_check_sample_request(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haiqu_check_sample_request() RETURNS trigger
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


--
-- Name: haiqu_check_sample_shipment(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haiqu_check_sample_shipment() RETURNS trigger
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


--
-- Name: haiqu_check_sample_shipment_item(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haiqu_check_sample_shipment_item() RETURNS trigger
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


--
-- Name: haiqu_guard_customer_merge_member(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haiqu_guard_customer_merge_member() RETURNS trigger
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


--
-- Name: haiqu_guard_quotation_line(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haiqu_guard_quotation_line() RETURNS trigger
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


--
-- Name: haiqu_guard_quotation_tier(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haiqu_guard_quotation_tier() RETURNS trigger
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


--
-- Name: haiqu_guard_quotation_version(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.haiqu_guard_quotation_version() RETURNS trigger
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


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: approval_request; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approval_request (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    approval_type character varying(50) NOT NULL,
    status character varying(20) NOT NULL,
    request_reason text NOT NULL,
    decision_note text NOT NULL,
    submitted_at timestamp with time zone NOT NULL,
    decided_at timestamp with time zone,
    current_approver_employee_id uuid NOT NULL,
    requested_by_employee_id uuid,
    CONSTRAINT approval_decision_time_consistent CHECK ((((decided_at IS NULL) AND ((status)::text = 'PENDING'::text)) OR ((decided_at IS NOT NULL) AND ((status)::text = ANY ((ARRAY['APPROVED'::character varying, 'REJECTED'::character varying])::text[]))) OR ((status)::text = 'CANCELLED'::text))),
    CONSTRAINT approval_status_valid CHECK (((status)::text = ANY ((ARRAY['PENDING'::character varying, 'APPROVED'::character varying, 'REJECTED'::character varying, 'CANCELLED'::character varying])::text[])))
);


--
-- Name: audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_log (
    id uuid NOT NULL,
    actor_employee_code_snapshot character varying(50) NOT NULL,
    actor_name_snapshot character varying(150) NOT NULL,
    object_type character varying(80) NOT NULL,
    object_id uuid NOT NULL,
    context_type character varying(80) NOT NULL,
    context_id uuid,
    action character varying(80) NOT NULL,
    before_data jsonb NOT NULL,
    after_data jsonb NOT NULL,
    request_id uuid,
    ip_address inet,
    user_agent character varying(500) NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    actor_employee_id uuid,
    CONSTRAINT audit_context_pair_consistent CHECK ((((context_id IS NULL) AND ((context_type)::text = ''::text)) OR ((NOT ((context_type)::text = ''::text)) AND (context_id IS NOT NULL))))
);


--
-- Name: auth_group; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_group (
    id integer NOT NULL,
    name character varying(150) NOT NULL
);


--
-- Name: auth_group_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_group ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_group_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_group_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_group_permissions (
    id bigint NOT NULL,
    group_id integer NOT NULL,
    permission_id integer NOT NULL
);


--
-- Name: auth_group_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_group_permissions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_group_permissions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_permission; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_permission (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    content_type_id integer NOT NULL,
    codename character varying(100) NOT NULL
);


--
-- Name: auth_permission_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_permission ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_permission_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_user; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_user (
    id integer NOT NULL,
    password character varying(128) NOT NULL,
    last_login timestamp with time zone,
    is_superuser boolean NOT NULL,
    username character varying(150) NOT NULL,
    first_name character varying(150) NOT NULL,
    last_name character varying(150) NOT NULL,
    email character varying(254) NOT NULL,
    is_staff boolean NOT NULL,
    is_active boolean NOT NULL,
    date_joined timestamp with time zone NOT NULL
);


--
-- Name: auth_user_groups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_user_groups (
    id bigint NOT NULL,
    user_id integer NOT NULL,
    group_id integer NOT NULL
);


--
-- Name: auth_user_groups_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_user_groups ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_user_groups_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_user_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_user ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_user_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_user_user_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_user_user_permissions (
    id bigint NOT NULL,
    user_id integer NOT NULL,
    permission_id integer NOT NULL
);


--
-- Name: auth_user_user_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_user_user_permissions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_user_user_permissions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: automation_execution; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.automation_execution (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    automation_code character varying(80) NOT NULL,
    idempotency_key character varying(200) NOT NULL,
    status character varying(20) NOT NULL,
    attempt_count integer NOT NULL,
    next_retry_at timestamp with time zone,
    last_error text NOT NULL,
    input_data jsonb NOT NULL,
    result_data jsonb NOT NULL,
    CONSTRAINT automation_code_uppercase CHECK (((automation_code)::text = upper((automation_code)::text))),
    CONSTRAINT automation_execution_attempt_count_check CHECK ((attempt_count >= 0)),
    CONSTRAINT automation_status_valid CHECK (((status)::text = ANY ((ARRAY['PENDING'::character varying, 'RUNNING'::character varying, 'SUCCEEDED'::character varying, 'RETRY'::character varying, 'FAILED'::character varying])::text[])))
);


--
-- Name: business_file; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.business_file (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    archive_reason character varying(500) NOT NULL,
    original_name character varying(255) NOT NULL,
    storage_key character varying(500) NOT NULL,
    content_type character varying(150) NOT NULL,
    size_bytes bigint NOT NULL,
    content_hash character varying(128) NOT NULL,
    scan_status character varying(20) NOT NULL,
    scanned_at timestamp with time zone,
    scan_message character varying(500) NOT NULL,
    archived_by_employee_id uuid,
    uploaded_by_employee_id uuid,
    CONSTRAINT business_file_scan_status_valid CHECK (((scan_status)::text = ANY ((ARRAY['PENDING'::character varying, 'CLEAN'::character varying, 'INFECTED'::character varying, 'FAILED'::character varying])::text[]))),
    CONSTRAINT business_file_size_bytes_check CHECK ((size_bytes >= 0))
);


--
-- Name: business_task; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.business_task (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    archive_reason character varying(500) NOT NULL,
    title character varying(250) NOT NULL,
    description text NOT NULL,
    status character varying(20) NOT NULL,
    priority character varying(20) NOT NULL,
    due_at timestamp with time zone,
    completed_at timestamp with time zone,
    automation_key character varying(200),
    archived_by_employee_id uuid,
    assignee_employee_id uuid NOT NULL,
    created_by_employee_id uuid,
    CONSTRAINT task_completed_has_time CHECK ((((completed_at IS NOT NULL) AND ((status)::text = 'COMPLETED'::text)) OR (NOT ((status)::text = 'COMPLETED'::text)))),
    CONSTRAINT task_priority_valid CHECK (((priority)::text = ANY ((ARRAY['LOW'::character varying, 'NORMAL'::character varying, 'HIGH'::character varying, 'URGENT'::character varying])::text[]))),
    CONSTRAINT task_status_valid CHECK (((status)::text = ANY ((ARRAY['PENDING'::character varying, 'IN_PROGRESS'::character varying, 'COMPLETED'::character varying, 'CANCELLED'::character varying])::text[])))
);


--
-- Name: communication_contact_participant; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.communication_contact_participant (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    participant_role character varying(20) NOT NULL,
    customer_contact_id uuid NOT NULL,
    communication_id uuid NOT NULL
);


--
-- Name: communication_employee_participant; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.communication_employee_participant (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    participant_role character varying(20) NOT NULL,
    employee_id uuid NOT NULL,
    communication_id uuid NOT NULL
);


--
-- Name: communication_file_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.communication_file_link (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    file_role character varying(50) NOT NULL,
    business_file_id uuid NOT NULL,
    communication_id uuid NOT NULL
);


--
-- Name: communication_inquiry_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.communication_inquiry_link (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    inquiry_id uuid NOT NULL,
    communication_id uuid NOT NULL
);


--
-- Name: communication_quotation_version_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.communication_quotation_version_link (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    quotation_version_id uuid NOT NULL,
    communication_id uuid NOT NULL
);


--
-- Name: communication_sample_request_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.communication_sample_request_link (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    sample_request_id uuid NOT NULL,
    communication_id uuid NOT NULL
);


--
-- Name: communication_task_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.communication_task_link (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    is_primary_source boolean NOT NULL,
    business_task_id uuid NOT NULL,
    communication_id uuid NOT NULL
);


--
-- Name: customer_account; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_account (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    archive_reason character varying(500) NOT NULL,
    account_code character varying(50) NOT NULL,
    account_name character varying(250) NOT NULL,
    english_name character varying(250) NOT NULL,
    short_name character varying(150) NOT NULL,
    lifecycle_stage character varying(20) NOT NULL,
    primary_country_code character varying(2) NOT NULL,
    primary_website_url character varying(500) NOT NULL,
    source_system character varying(50) NOT NULL,
    external_id character varying(150) NOT NULL,
    notes text NOT NULL,
    archived_by_employee_id uuid,
    CONSTRAINT customer_account_code_uppercase CHECK (((account_code)::text = upper((account_code)::text))),
    CONSTRAINT customer_lifecycle_valid CHECK (((lifecycle_stage)::text = ANY ((ARRAY['PROSPECT'::character varying, 'ACTIVE'::character varying, 'DORMANT'::character varying, 'CLOSED'::character varying])::text[]))),
    CONSTRAINT customer_source_pair_consistent CHECK (((((external_id)::text = ''::text) AND ((source_system)::text = ''::text)) OR ((NOT ((source_system)::text = ''::text)) AND (NOT ((external_id)::text = ''::text)))))
);


--
-- Name: customer_assignment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_assignment (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    assignment_role character varying(30) NOT NULL,
    effective_from timestamp with time zone NOT NULL,
    effective_to timestamp with time zone,
    reason character varying(500) NOT NULL,
    assigned_by_employee_id uuid,
    customer_account_id uuid NOT NULL,
    employee_id uuid NOT NULL,
    CONSTRAINT customer_assignment_valid_range CHECK (((effective_to IS NULL) OR (effective_to > effective_from)))
);


--
-- Name: customer_attention_review; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_attention_review (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    reason text NOT NULL,
    effective_from timestamp with time zone NOT NULL,
    effective_to timestamp with time zone,
    attention_level_item_id uuid NOT NULL,
    customer_account_id uuid NOT NULL,
    reviewed_by_employee_id uuid NOT NULL,
    CONSTRAINT cust_attention_valid_range CHECK (((effective_to IS NULL) OR (effective_to > effective_from)))
);


--
-- Name: customer_communication; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_communication (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    archive_reason character varying(500) NOT NULL,
    communication_type character varying(50) NOT NULL,
    direction character varying(20) NOT NULL,
    subject character varying(250) NOT NULL,
    content text NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    source_system character varying(50) NOT NULL,
    external_id character varying(150) NOT NULL,
    archived_by_employee_id uuid,
    created_by_employee_id uuid,
    customer_account_id uuid NOT NULL,
    CONSTRAINT communication_source_pair_consistent CHECK (((((external_id)::text = ''::text) AND ((source_system)::text = ''::text)) OR ((NOT ((source_system)::text = ''::text)) AND (NOT ((external_id)::text = ''::text)))))
);


--
-- Name: customer_contact; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_contact (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    archive_reason character varying(500) NOT NULL,
    display_name character varying(150) NOT NULL,
    position_title character varying(150) NOT NULL,
    status character varying(20) NOT NULL,
    notes text NOT NULL,
    archived_by_employee_id uuid,
    customer_account_id uuid NOT NULL,
    source_contact_id uuid,
    transaction_entity_id uuid,
    CONSTRAINT contact_source_not_self CHECK ((NOT ((id = source_contact_id) AND (source_contact_id IS NOT NULL)))),
    CONSTRAINT contact_status_valid CHECK (((status)::text = ANY ((ARRAY['ACTIVE'::character varying, 'INACTIVE'::character varying, 'LEFT'::character varying])::text[])))
);


--
-- Name: customer_contact_method; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_contact_method (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    archive_reason character varying(500) NOT NULL,
    method_type character varying(20) NOT NULL,
    raw_value character varying(255) NOT NULL,
    normalized_value character varying(255) NOT NULL,
    normalization_version smallint NOT NULL,
    normalized_at timestamp with time zone NOT NULL,
    is_primary boolean NOT NULL,
    is_preferred boolean NOT NULL,
    verification_status character varying(20) NOT NULL,
    archived_by_employee_id uuid,
    customer_contact_id uuid NOT NULL,
    CONSTRAINT customer_contact_method_normalization_version_check CHECK ((normalization_version >= 0))
);


--
-- Name: customer_contact_role; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_contact_role (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    role_type character varying(30) NOT NULL,
    effective_from timestamp with time zone NOT NULL,
    effective_to timestamp with time zone,
    notes character varying(500) NOT NULL,
    customer_contact_id uuid NOT NULL,
    CONSTRAINT contact_role_valid_range CHECK (((effective_to IS NULL) OR (effective_to > effective_from)))
);


--
-- Name: customer_data_access_grant; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_data_access_grant (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    effective_from timestamp with time zone NOT NULL,
    effective_to timestamp with time zone,
    revoked_at timestamp with time zone,
    reason character varying(500) NOT NULL,
    customer_account_id uuid NOT NULL,
    employee_id uuid NOT NULL,
    granted_by_employee_id uuid,
    permission_id integer NOT NULL,
    revoked_by_employee_id uuid,
    CONSTRAINT cust_grant_valid_range CHECK (((effective_to IS NULL) OR (effective_to > effective_from)))
);


--
-- Name: customer_duplicate_candidate; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_duplicate_candidate (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    confidence_score numeric(5,4) NOT NULL,
    matched_fields jsonb NOT NULL,
    decision character varying(20) NOT NULL,
    customer_account_id uuid NOT NULL,
    duplicate_case_id uuid NOT NULL,
    CONSTRAINT cust_dup_decision_valid CHECK (((decision)::text = ANY ((ARRAY['PENDING'::character varying, 'DUPLICATE'::character varying, 'NOT_DUPLICATE'::character varying, 'SURVIVOR'::character varying])::text[]))),
    CONSTRAINT cust_dup_score_range CHECK (((confidence_score >= (0)::numeric) AND (confidence_score <= (1)::numeric)))
);


--
-- Name: customer_duplicate_case; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_duplicate_case (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    status character varying(20) NOT NULL,
    matching_strategy_version character varying(50) NOT NULL,
    notes text NOT NULL,
    reviewer_employee_id uuid,
    CONSTRAINT cust_duplicate_case_status_valid CHECK (((status)::text = ANY ((ARRAY['OPEN'::character varying, 'REVIEWING'::character varying, 'RESOLVED'::character varying, 'DISMISSED'::character varying])::text[])))
);


--
-- Name: customer_entity_address; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_entity_address (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    archive_reason character varying(500) NOT NULL,
    address_code character varying(50) NOT NULL,
    label character varying(150) NOT NULL,
    country_code character varying(2) NOT NULL,
    state_province character varying(150) NOT NULL,
    city character varying(150) NOT NULL,
    postal_code character varying(30) NOT NULL,
    address_line1 character varying(250) NOT NULL,
    address_line2 character varying(250) NOT NULL,
    recipient_name character varying(150) NOT NULL,
    recipient_phone character varying(50) NOT NULL,
    is_verified boolean NOT NULL,
    archived_by_employee_id uuid,
    transaction_entity_id uuid NOT NULL,
    CONSTRAINT cust_address_code_uppercase CHECK (((address_code)::text = upper((address_code)::text)))
);


--
-- Name: customer_entity_address_usage; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_entity_address_usage (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    usage_type character varying(30) NOT NULL,
    effective_from timestamp with time zone NOT NULL,
    effective_to timestamp with time zone,
    entity_address_id uuid NOT NULL,
    CONSTRAINT cust_address_usage_valid_range CHECK (((effective_to IS NULL) OR (effective_to > effective_from)))
);


--
-- Name: customer_file_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_file_link (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    file_role character varying(50) NOT NULL,
    business_file_id uuid NOT NULL,
    customer_account_id uuid NOT NULL
);


--
-- Name: customer_historical_transaction_confirmation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_historical_transaction_confirmation (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    status character varying(20) NOT NULL,
    basis_note text NOT NULL,
    confirmed_at timestamp with time zone,
    confirmed_by_employee_id uuid,
    customer_account_id uuid NOT NULL,
    CONSTRAINT cust_history_confirm_status_valid CHECK (((status)::text = ANY ((ARRAY['PENDING'::character varying, 'CONFIRMED'::character varying, 'REJECTED'::character varying])::text[])))
);


--
-- Name: customer_merge_change; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_merge_change (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    sequence_number integer NOT NULL,
    object_type character varying(80) NOT NULL,
    object_id uuid NOT NULL,
    change_data jsonb NOT NULL,
    merge_operation_id uuid NOT NULL,
    CONSTRAINT customer_merge_change_sequence_number_check CHECK ((sequence_number >= 0))
);


--
-- Name: customer_merge_member; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_merge_member (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    member_role character varying(20) NOT NULL,
    customer_account_id uuid NOT NULL,
    merge_operation_id uuid NOT NULL
);


--
-- Name: customer_merge_operation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_merge_operation (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    status character varying(20) NOT NULL,
    reason text NOT NULL,
    executed_at timestamp with time zone,
    duplicate_case_id uuid,
    executed_by_employee_id uuid,
    CONSTRAINT cust_merge_status_valid CHECK (((status)::text = ANY ((ARRAY['PLANNED'::character varying, 'COMPLETED'::character varying, 'FAILED'::character varying, 'ROLLED_BACK'::character varying])::text[])))
);


--
-- Name: customer_task_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_task_link (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    is_primary_source boolean NOT NULL,
    business_task_id uuid NOT NULL,
    customer_account_id uuid NOT NULL
);


--
-- Name: customer_timeline_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_timeline_event (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    event_key character varying(200) NOT NULL,
    source_type character varying(80) NOT NULL,
    source_id uuid NOT NULL,
    event_type character varying(80) NOT NULL,
    title character varying(250) NOT NULL,
    summary text NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    event_data jsonb NOT NULL,
    customer_account_id uuid NOT NULL
);


--
-- Name: customer_transaction_entity; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_transaction_entity (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    archive_reason character varying(500) NOT NULL,
    entity_code character varying(50) NOT NULL,
    entity_type character varying(20) NOT NULL,
    legal_name character varying(250) NOT NULL,
    english_legal_name character varying(250) NOT NULL,
    registration_country_code character varying(2) NOT NULL,
    registration_number character varying(100) NOT NULL,
    tax_country_code character varying(2) NOT NULL,
    tax_identifier character varying(100) NOT NULL,
    notes text NOT NULL,
    archived_by_employee_id uuid,
    customer_account_id uuid NOT NULL,
    CONSTRAINT cust_entity_code_uppercase CHECK (((entity_code)::text = upper((entity_code)::text)))
);


--
-- Name: customer_transaction_entity_role; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_transaction_entity_role (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    role_type character varying(30) NOT NULL,
    effective_from timestamp with time zone NOT NULL,
    effective_to timestamp with time zone,
    transaction_entity_id uuid NOT NULL,
    CONSTRAINT cust_entity_role_valid_range CHECK (((effective_to IS NULL) OR (effective_to > effective_from)))
);


--
-- Name: customer_transfer_request; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customer_transfer_request (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    status character varying(20) NOT NULL,
    request_reason text NOT NULL,
    decision_note text NOT NULL,
    submitted_at timestamp with time zone NOT NULL,
    decided_at timestamp with time zone,
    customer_account_id uuid NOT NULL,
    decided_by_employee_id uuid,
    from_employee_id uuid NOT NULL,
    requested_by_employee_id uuid,
    to_employee_id uuid NOT NULL,
    CONSTRAINT cust_transfer_different_emp CHECK ((NOT (from_employee_id = to_employee_id))),
    CONSTRAINT cust_transfer_status_valid CHECK (((status)::text = ANY ((ARRAY['PENDING'::character varying, 'APPROVED'::character varying, 'REJECTED'::character varying, 'CANCELLED'::character varying])::text[])))
);


--
-- Name: django_admin_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_admin_log (
    id integer NOT NULL,
    action_time timestamp with time zone NOT NULL,
    object_id text,
    object_repr character varying(200) NOT NULL,
    action_flag smallint NOT NULL,
    change_message text NOT NULL,
    content_type_id integer,
    user_id integer NOT NULL,
    CONSTRAINT django_admin_log_action_flag_check CHECK ((action_flag >= 0))
);


--
-- Name: django_admin_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_admin_log ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_admin_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_content_type; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_content_type (
    id integer NOT NULL,
    app_label character varying(100) NOT NULL,
    model character varying(100) NOT NULL
);


--
-- Name: django_content_type_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_content_type ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_content_type_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_migrations (
    id bigint NOT NULL,
    app character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    applied timestamp with time zone NOT NULL
);


--
-- Name: django_migrations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_migrations ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_migrations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_session (
    session_key character varying(40) NOT NULL,
    session_data text NOT NULL,
    expire_date timestamp with time zone NOT NULL
);


--
-- Name: employee; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.employee (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    archive_reason character varying(500) NOT NULL,
    employee_code character varying(50) NOT NULL,
    display_name character varying(150) NOT NULL,
    email character varying(254) NOT NULL,
    phone character varying(50) NOT NULL,
    status character varying(20) NOT NULL,
    hired_at date,
    left_at date,
    archived_by_employee_id uuid,
    user_id integer,
    CONSTRAINT employee_code_uppercase CHECK (((employee_code)::text = upper((employee_code)::text))),
    CONSTRAINT employee_status_valid CHECK (((status)::text = ANY ((ARRAY['ACTIVE'::character varying, 'INACTIVE'::character varying, 'LEFT'::character varying])::text[]))),
    CONSTRAINT employee_valid_employment_dates CHECK (((left_at IS NULL) OR (hired_at IS NULL) OR (left_at >= hired_at)))
);


--
-- Name: employee_organization_assignment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.employee_organization_assignment (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    position_title character varying(150) NOT NULL,
    is_primary boolean NOT NULL,
    effective_from timestamp with time zone NOT NULL,
    effective_to timestamp with time zone,
    assigned_by_employee_id uuid,
    employee_id uuid NOT NULL,
    organization_unit_id uuid NOT NULL,
    CONSTRAINT emp_org_valid_effective_range CHECK (((effective_to IS NULL) OR (effective_to > effective_from)))
);


--
-- Name: employee_role_assignment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.employee_role_assignment (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    effective_from timestamp with time zone NOT NULL,
    effective_to timestamp with time zone,
    assigned_by_employee_id uuid,
    employee_id uuid NOT NULL,
    role_profile_id uuid NOT NULL,
    CONSTRAINT emp_role_valid_effective_range CHECK (((effective_to IS NULL) OR (effective_to > effective_from)))
);


--
-- Name: haiqu_customer_number_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.haiqu_customer_number_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: haiqu_inquiry_number_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.haiqu_inquiry_number_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: haiqu_quotation_number_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.haiqu_quotation_number_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: haiqu_sample_number_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.haiqu_sample_number_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: import_batch; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.import_batch (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    import_type character varying(80) NOT NULL,
    status character varying(30) NOT NULL,
    total_count integer NOT NULL,
    success_count integer NOT NULL,
    failure_count integer NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    config_data jsonb NOT NULL,
    error_summary text NOT NULL,
    created_by_employee_id uuid,
    source_file_id uuid NOT NULL,
    CONSTRAINT import_batch_counts_within_total CHECK ((total_count >= (success_count + failure_count))),
    CONSTRAINT import_batch_failure_count_check CHECK ((failure_count >= 0)),
    CONSTRAINT import_batch_status_valid CHECK (((status)::text = ANY ((ARRAY['PENDING'::character varying, 'PROCESSING'::character varying, 'COMPLETED'::character varying, 'PARTIAL_FAILED'::character varying, 'FAILED'::character varying, 'CANCELLED'::character varying])::text[]))),
    CONSTRAINT import_batch_success_count_check CHECK ((success_count >= 0)),
    CONSTRAINT import_batch_total_count_check CHECK ((total_count >= 0)),
    CONSTRAINT import_batch_valid_times CHECK (((finished_at IS NULL) OR (started_at IS NULL) OR (finished_at >= started_at)))
);


--
-- Name: import_record; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.import_record (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    row_number integer NOT NULL,
    status character varying(20) NOT NULL,
    raw_data jsonb NOT NULL,
    error_message text NOT NULL,
    target_type character varying(80) NOT NULL,
    target_id uuid,
    import_batch_id uuid NOT NULL,
    CONSTRAINT import_record_row_number_check CHECK ((row_number >= 0)),
    CONSTRAINT import_record_status_valid CHECK (((status)::text = ANY ((ARRAY['PENDING'::character varying, 'SUCCEEDED'::character varying, 'FAILED'::character varying, 'SKIPPED'::character varying])::text[]))),
    CONSTRAINT import_record_target_pair_consistent CHECK ((((target_id IS NULL) AND ((target_type)::text = ''::text)) OR ((NOT ((target_type)::text = ''::text)) AND (target_id IS NOT NULL))))
);


--
-- Name: inquiry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inquiry (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    archive_reason character varying(500) NOT NULL,
    inquiry_number character varying(50) NOT NULL,
    status character varying(20) NOT NULL,
    inquiry_source character varying(50) NOT NULL,
    subject character varying(250) NOT NULL,
    description text NOT NULL,
    received_at timestamp with time zone NOT NULL,
    requested_due_at timestamp with time zone,
    submitted_at timestamp with time zone,
    source_system character varying(50) NOT NULL,
    external_id character varying(150) NOT NULL,
    archived_by_employee_id uuid,
    customer_account_id uuid NOT NULL,
    customer_contact_id uuid,
    owner_employee_id uuid NOT NULL,
    transaction_entity_id uuid,
    CONSTRAINT inquiry_number_uppercase CHECK (((inquiry_number)::text = upper((inquiry_number)::text))),
    CONSTRAINT inquiry_source_pair_consistent CHECK (((((external_id)::text = ''::text) AND ((source_system)::text = ''::text)) OR ((NOT ((source_system)::text = ''::text)) AND (NOT ((external_id)::text = ''::text))))),
    CONSTRAINT inquiry_status_valid CHECK (((status)::text = ANY ((ARRAY['DRAFT'::character varying, 'SUBMITTED'::character varying, 'IN_PROGRESS'::character varying, 'QUOTED'::character varying, 'CLOSED'::character varying, 'CANCELLED'::character varying])::text[])))
);


--
-- Name: inquiry_file_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inquiry_file_link (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    file_role character varying(50) NOT NULL,
    business_file_id uuid NOT NULL,
    inquiry_id uuid NOT NULL
);


--
-- Name: inquiry_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inquiry_item (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    line_number integer NOT NULL,
    product_description character varying(500) NOT NULL,
    specification text NOT NULL,
    quantity numeric(18,4) NOT NULL,
    unit_code character varying(30) NOT NULL,
    target_unit_price numeric(18,4),
    target_currency_code character varying(3) NOT NULL,
    notes text NOT NULL,
    inquiry_id uuid NOT NULL,
    CONSTRAINT inquiry_item_line_number_check CHECK ((line_number >= 0)),
    CONSTRAINT inquiry_item_qty_positive CHECK ((quantity > (0)::numeric)),
    CONSTRAINT inquiry_item_target_price_nonneg CHECK (((target_unit_price IS NULL) OR (target_unit_price >= (0)::numeric)))
);


--
-- Name: inquiry_sla_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inquiry_sla_link (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    inquiry_id uuid NOT NULL,
    sla_tracking_id uuid NOT NULL
);


--
-- Name: inquiry_task_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inquiry_task_link (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    is_primary_source boolean NOT NULL,
    business_task_id uuid NOT NULL,
    inquiry_id uuid NOT NULL
);


--
-- Name: organization_unit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.organization_unit (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    archive_reason character varying(500) NOT NULL,
    unit_code character varying(50) NOT NULL,
    unit_name character varying(200) NOT NULL,
    status character varying(20) NOT NULL,
    sort_order integer NOT NULL,
    archived_by_employee_id uuid,
    parent_id uuid,
    CONSTRAINT org_unit_code_uppercase CHECK (((unit_code)::text = upper((unit_code)::text))),
    CONSTRAINT org_unit_parent_not_self CHECK ((NOT ((id = parent_id) AND (parent_id IS NOT NULL)))),
    CONSTRAINT org_unit_status_valid CHECK (((status)::text = ANY ((ARRAY['ACTIVE'::character varying, 'INACTIVE'::character varying])::text[]))),
    CONSTRAINT organization_unit_sort_order_check CHECK ((sort_order >= 0))
);


--
-- Name: quotation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quotation (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    archive_reason character varying(500) NOT NULL,
    quotation_number character varying(50) NOT NULL,
    outcome_status character varying(20) NOT NULL,
    subject character varying(250) NOT NULL,
    outcome_note text NOT NULL,
    archived_by_employee_id uuid,
    customer_account_id uuid NOT NULL,
    owner_employee_id uuid NOT NULL,
    source_inquiry_id uuid,
    transaction_entity_id uuid NOT NULL,
    accepted_version_id uuid,
    CONSTRAINT quotation_number_uppercase CHECK (((quotation_number)::text = upper((quotation_number)::text))),
    CONSTRAINT quotation_outcome_status_valid CHECK (((outcome_status)::text = ANY ((ARRAY['OPEN'::character varying, 'WON'::character varying, 'LOST'::character varying, 'CANCELLED'::character varying])::text[])))
);


--
-- Name: quotation_dispatch_record; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quotation_dispatch_record (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    channel character varying(50) NOT NULL,
    recipient_snapshot jsonb NOT NULL,
    dispatched_at timestamp with time zone NOT NULL,
    external_reference character varying(250) NOT NULL,
    follow_up_due_at timestamp with time zone,
    follow_up_status character varying(20) NOT NULL,
    notes text NOT NULL,
    dispatched_by_employee_id uuid,
    quotation_version_id uuid NOT NULL,
    CONSTRAINT quote_followup_status_valid CHECK (((follow_up_status)::text = ANY ((ARRAY['PENDING'::character varying, 'COMPLETED'::character varying, 'CANCELLED'::character varying])::text[])))
);


--
-- Name: quotation_document; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quotation_document (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    document_type character varying(20) NOT NULL,
    is_formal boolean NOT NULL,
    generated_at timestamp with time zone NOT NULL,
    snapshot_hash character varying(128) NOT NULL,
    business_file_id uuid NOT NULL,
    generated_by_employee_id uuid,
    quotation_version_id uuid NOT NULL
);


--
-- Name: quotation_file_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quotation_file_link (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    file_role character varying(50) NOT NULL,
    business_file_id uuid NOT NULL,
    quotation_version_id uuid NOT NULL
);


--
-- Name: quotation_line; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quotation_line (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    line_number integer NOT NULL,
    product_description_snapshot character varying(500) NOT NULL,
    specification_snapshot text NOT NULL,
    quantity numeric(18,4) NOT NULL,
    unit_code character varying(30) NOT NULL,
    unit_price numeric(18,4) NOT NULL,
    discount_rate numeric(7,6) NOT NULL,
    line_total numeric(18,4) NOT NULL,
    notes text NOT NULL,
    quotation_version_id uuid NOT NULL,
    CONSTRAINT quotation_line_discount_range CHECK (((discount_rate >= (0)::numeric) AND (discount_rate <= (1)::numeric))),
    CONSTRAINT quotation_line_line_number_check CHECK ((line_number >= 0)),
    CONSTRAINT quotation_line_price_nonneg CHECK ((unit_price >= (0)::numeric)),
    CONSTRAINT quotation_line_qty_positive CHECK ((quantity > (0)::numeric)),
    CONSTRAINT quotation_line_total_nonneg CHECK ((line_total >= (0)::numeric))
);


--
-- Name: quotation_quantity_tier; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quotation_quantity_tier (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    min_quantity numeric(18,4) NOT NULL,
    max_quantity numeric(18,4),
    unit_price numeric(18,4) NOT NULL,
    quotation_line_id uuid NOT NULL,
    CONSTRAINT quote_tier_min_qty_positive CHECK ((min_quantity > (0)::numeric)),
    CONSTRAINT quote_tier_price_nonneg CHECK ((unit_price >= (0)::numeric)),
    CONSTRAINT quote_tier_valid_range CHECK (((max_quantity IS NULL) OR (max_quantity > min_quantity)))
);


--
-- Name: quotation_template; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quotation_template (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    archive_reason character varying(500) NOT NULL,
    template_code character varying(50) NOT NULL,
    template_name character varying(200) NOT NULL,
    template_version integer NOT NULL,
    requires_approval boolean NOT NULL,
    template_config jsonb NOT NULL,
    archived_by_employee_id uuid,
    CONSTRAINT quotation_template_template_version_check CHECK ((template_version >= 0)),
    CONSTRAINT quote_template_code_uppercase CHECK (((template_code)::text = upper((template_code)::text)))
);


--
-- Name: quotation_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quotation_version (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    version_number integer NOT NULL,
    status character varying(20) NOT NULL,
    currency_code character varying(3) NOT NULL,
    language_code character varying(20) NOT NULL,
    subtotal_amount numeric(18,4) NOT NULL,
    discount_amount numeric(18,4) NOT NULL,
    tax_amount numeric(18,4) NOT NULL,
    total_amount numeric(18,4) NOT NULL,
    issued_at timestamp with time zone,
    valid_until date,
    locked_at timestamp with time zone,
    transaction_entity_snapshot jsonb NOT NULL,
    address_snapshot jsonb NOT NULL,
    contact_snapshot jsonb NOT NULL,
    template_snapshot jsonb NOT NULL,
    terms_snapshot jsonb NOT NULL,
    notes text NOT NULL,
    locked_by_employee_id uuid,
    quotation_id uuid NOT NULL,
    quotation_template_id uuid,
    CONSTRAINT quotation_lock_state_consistent CHECK ((((locked_at IS NULL) AND ((status)::text = 'DRAFT'::text)) OR ((NOT ((status)::text = 'DRAFT'::text)) AND (locked_at IS NOT NULL)))),
    CONSTRAINT quotation_version_amounts_nonneg CHECK (((subtotal_amount >= (0)::numeric) AND (discount_amount >= (0)::numeric) AND (tax_amount >= (0)::numeric) AND (total_amount >= (0)::numeric))),
    CONSTRAINT quotation_version_status_valid CHECK (((status)::text = ANY ((ARRAY['DRAFT'::character varying, 'LOCKED'::character varying, 'ISSUED'::character varying, 'SENT'::character varying, 'SUPERSEDED'::character varying, 'VOID'::character varying])::text[]))),
    CONSTRAINT quotation_version_version_number_check CHECK ((version_number >= 0))
);


--
-- Name: quotation_version_approval_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quotation_version_approval_link (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    approval_request_id uuid NOT NULL,
    quotation_version_id uuid NOT NULL
);


--
-- Name: quotation_version_sla_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quotation_version_sla_link (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    quotation_version_id uuid NOT NULL,
    sla_tracking_id uuid NOT NULL
);


--
-- Name: quotation_version_task_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quotation_version_task_link (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    is_primary_source boolean NOT NULL,
    business_task_id uuid NOT NULL,
    quotation_version_id uuid NOT NULL
);


--
-- Name: reference_dictionary; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.reference_dictionary (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    archive_reason character varying(500) NOT NULL,
    category_code character varying(50) NOT NULL,
    item_code character varying(50) NOT NULL,
    display_name character varying(150) NOT NULL,
    description character varying(500) NOT NULL,
    status character varying(20) NOT NULL,
    sort_order integer NOT NULL,
    extra_data jsonb NOT NULL,
    archived_by_employee_id uuid,
    CONSTRAINT ref_dict_category_uppercase CHECK (((category_code)::text = upper((category_code)::text))),
    CONSTRAINT ref_dict_item_uppercase CHECK (((item_code)::text = upper((item_code)::text))),
    CONSTRAINT ref_dict_status_valid CHECK (((status)::text = ANY ((ARRAY['ACTIVE'::character varying, 'INACTIVE'::character varying])::text[]))),
    CONSTRAINT reference_dictionary_sort_order_check CHECK ((sort_order >= 0))
);


--
-- Name: role_profile; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.role_profile (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    archive_reason character varying(500) NOT NULL,
    role_code character varying(50) NOT NULL,
    display_name character varying(150) NOT NULL,
    description text NOT NULL,
    archived_by_employee_id uuid,
    auth_group_id integer NOT NULL,
    CONSTRAINT role_profile_code_uppercase CHECK (((role_code)::text = upper((role_code)::text)))
);


--
-- Name: sample_approval_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sample_approval_link (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    approval_request_id uuid NOT NULL,
    sample_request_id uuid NOT NULL
);


--
-- Name: sample_fee_record; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sample_fee_record (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    fee_decision character varying(20) NOT NULL,
    amount numeric(18,4) NOT NULL,
    currency_code character varying(3) NOT NULL,
    verification_status character varying(30) NOT NULL,
    decision_reason text NOT NULL,
    decided_at timestamp with time zone,
    superseded_at timestamp with time zone,
    decided_by_employee_id uuid,
    sample_request_id uuid NOT NULL,
    CONSTRAINT sample_fee_amount_nonneg CHECK ((amount >= (0)::numeric)),
    CONSTRAINT sample_fee_decision_amount_match CHECK ((((amount > (0)::numeric) AND ((fee_decision)::text = 'PAID'::text)) OR ((amount = (0)::numeric) AND ((fee_decision)::text = ANY ((ARRAY['FREE'::character varying, 'WAIVED'::character varying])::text[]))) OR ((fee_decision)::text = 'PENDING'::text))),
    CONSTRAINT sample_fee_decision_valid CHECK (((fee_decision)::text = ANY ((ARRAY['PENDING'::character varying, 'FREE'::character varying, 'PAID'::character varying, 'WAIVED'::character varying])::text[]))),
    CONSTRAINT sample_fee_verify_status_valid CHECK (((verification_status)::text = ANY ((ARRAY['NOT_REQUIRED'::character varying, 'EVIDENCE_UPLOADED'::character varying, 'MANUALLY_CONFIRMED'::character varying, 'REJECTED'::character varying])::text[])))
);


--
-- Name: sample_feedback; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sample_feedback (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    feedback_type character varying(20) NOT NULL,
    feedback_content text NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    customer_contact_id uuid,
    recorded_by_employee_id uuid,
    sample_request_id uuid NOT NULL
);


--
-- Name: sample_file_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sample_file_link (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    file_role character varying(50) NOT NULL,
    business_file_id uuid NOT NULL,
    sample_request_id uuid NOT NULL
);


--
-- Name: sample_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sample_item (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    line_number integer NOT NULL,
    product_description_snapshot character varying(500) NOT NULL,
    specification_snapshot text NOT NULL,
    requested_quantity numeric(18,4) NOT NULL,
    unit_code character varying(30) NOT NULL,
    notes text NOT NULL,
    sample_request_id uuid NOT NULL,
    CONSTRAINT sample_item_line_number_check CHECK ((line_number >= 0)),
    CONSTRAINT sample_item_qty_positive CHECK ((requested_quantity > (0)::numeric))
);


--
-- Name: sample_request; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sample_request (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    archive_reason character varying(500) NOT NULL,
    request_number character varying(50) NOT NULL,
    status character varying(30) NOT NULL,
    purpose text NOT NULL,
    requested_at timestamp with time zone NOT NULL,
    requested_due_at timestamp with time zone,
    notes text NOT NULL,
    archived_by_employee_id uuid,
    customer_account_id uuid NOT NULL,
    customer_contact_id uuid,
    owner_employee_id uuid NOT NULL,
    source_inquiry_id uuid,
    source_quotation_version_id uuid,
    transaction_entity_id uuid,
    CONSTRAINT sample_request_number_uppercase CHECK (((request_number)::text = upper((request_number)::text))),
    CONSTRAINT sample_request_one_source_max CHECK (((source_inquiry_id IS NULL) OR (source_quotation_version_id IS NULL))),
    CONSTRAINT sample_request_status_valid CHECK (((status)::text = ANY ((ARRAY['DRAFT'::character varying, 'PENDING'::character varying, 'PREPARING'::character varying, 'SHIPPED'::character varying, 'FEEDBACK_PENDING'::character varying, 'COMPLETED'::character varying, 'CANCELLED'::character varying])::text[])))
);


--
-- Name: sample_shipment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sample_shipment (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    status character varying(20) NOT NULL,
    carrier_code character varying(50) NOT NULL,
    tracking_number character varying(150) NOT NULL,
    recipient_snapshot jsonb NOT NULL,
    address_snapshot jsonb NOT NULL,
    shipped_at timestamp with time zone,
    delivered_at timestamp with time zone,
    fee_warning_acknowledged boolean NOT NULL,
    fee_warning_acknowledged_at timestamp with time zone,
    notes text NOT NULL,
    fee_warning_acknowledged_by_employee_id uuid,
    sample_request_id uuid NOT NULL,
    shipped_by_employee_id uuid,
    CONSTRAINT sample_shipment_status_valid CHECK (((status)::text = ANY ((ARRAY['PREPARING'::character varying, 'SHIPPED'::character varying, 'DELIVERED'::character varying, 'EXCEPTION'::character varying, 'CANCELLED'::character varying])::text[])))
);


--
-- Name: sample_shipment_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sample_shipment_item (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    shipped_quantity numeric(18,4) NOT NULL,
    sample_item_id uuid NOT NULL,
    sample_shipment_id uuid NOT NULL,
    CONSTRAINT sample_ship_item_qty_positive CHECK ((shipped_quantity > (0)::numeric))
);


--
-- Name: sample_sla_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sample_sla_link (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    sample_request_id uuid NOT NULL,
    sla_tracking_id uuid NOT NULL
);


--
-- Name: sample_task_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sample_task_link (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    is_primary_source boolean NOT NULL,
    business_task_id uuid NOT NULL,
    sample_request_id uuid NOT NULL
);


--
-- Name: saved_view; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.saved_view (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    archive_reason character varying(500) NOT NULL,
    module_code character varying(80) NOT NULL,
    view_name character varying(150) NOT NULL,
    filter_definition jsonb NOT NULL,
    column_definition jsonb NOT NULL,
    sort_definition jsonb NOT NULL,
    is_default boolean NOT NULL,
    sort_order integer NOT NULL,
    archived_by_employee_id uuid,
    employee_id uuid NOT NULL,
    CONSTRAINT saved_view_sort_order_check CHECK ((sort_order >= 0))
);


--
-- Name: sla_policy; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sla_policy (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    archive_reason character varying(500) NOT NULL,
    policy_code character varying(50) NOT NULL,
    display_name character varying(150) NOT NULL,
    target_type character varying(50) NOT NULL,
    response_minutes integer,
    resolution_minutes integer,
    is_enabled boolean NOT NULL,
    config_data jsonb NOT NULL,
    archived_by_employee_id uuid,
    CONSTRAINT sla_policy_code_uppercase CHECK (((policy_code)::text = upper((policy_code)::text))),
    CONSTRAINT sla_policy_resolution_minutes_check CHECK ((resolution_minutes >= 0)),
    CONSTRAINT sla_policy_response_minutes_check CHECK ((response_minutes >= 0))
);


--
-- Name: sla_tracking; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sla_tracking (
    id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    status character varying(20) NOT NULL,
    started_at timestamp with time zone NOT NULL,
    next_deadline_at timestamp with time zone,
    breached_at timestamp with time zone,
    completed_at timestamp with time zone,
    tracking_data jsonb NOT NULL,
    sla_policy_id uuid NOT NULL,
    CONSTRAINT sla_deadline_after_start CHECK (((next_deadline_at IS NULL) OR (next_deadline_at >= started_at))),
    CONSTRAINT sla_tracking_status_valid CHECK (((status)::text = ANY ((ARRAY['RUNNING'::character varying, 'MET'::character varying, 'BREACHED'::character varying, 'CANCELLED'::character varying])::text[])))
);


--
-- Name: approval_request approval_request_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_request
    ADD CONSTRAINT approval_request_pkey PRIMARY KEY (id);


--
-- Name: audit_log audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);


--
-- Name: auth_group auth_group_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group
    ADD CONSTRAINT auth_group_name_key UNIQUE (name);


--
-- Name: auth_group_permissions auth_group_permissions_group_id_permission_id_0cd325b0_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_group_id_permission_id_0cd325b0_uniq UNIQUE (group_id, permission_id);


--
-- Name: auth_group_permissions auth_group_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_pkey PRIMARY KEY (id);


--
-- Name: auth_group auth_group_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group
    ADD CONSTRAINT auth_group_pkey PRIMARY KEY (id);


--
-- Name: auth_permission auth_permission_content_type_id_codename_01ab375a_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_content_type_id_codename_01ab375a_uniq UNIQUE (content_type_id, codename);


--
-- Name: auth_permission auth_permission_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_pkey PRIMARY KEY (id);


--
-- Name: auth_user_groups auth_user_groups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_groups
    ADD CONSTRAINT auth_user_groups_pkey PRIMARY KEY (id);


--
-- Name: auth_user_groups auth_user_groups_user_id_group_id_94350c0c_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_groups
    ADD CONSTRAINT auth_user_groups_user_id_group_id_94350c0c_uniq UNIQUE (user_id, group_id);


--
-- Name: auth_user auth_user_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user
    ADD CONSTRAINT auth_user_pkey PRIMARY KEY (id);


--
-- Name: auth_user_user_permissions auth_user_user_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_user_permissions
    ADD CONSTRAINT auth_user_user_permissions_pkey PRIMARY KEY (id);


--
-- Name: auth_user_user_permissions auth_user_user_permissions_user_id_permission_id_14a6b632_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_user_permissions
    ADD CONSTRAINT auth_user_user_permissions_user_id_permission_id_14a6b632_uniq UNIQUE (user_id, permission_id);


--
-- Name: auth_user auth_user_username_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user
    ADD CONSTRAINT auth_user_username_key UNIQUE (username);


--
-- Name: automation_execution automation_execution_idempotency_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_execution
    ADD CONSTRAINT automation_execution_idempotency_key_key UNIQUE (idempotency_key);


--
-- Name: automation_execution automation_execution_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_execution
    ADD CONSTRAINT automation_execution_pkey PRIMARY KEY (id);


--
-- Name: business_file business_file_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.business_file
    ADD CONSTRAINT business_file_pkey PRIMARY KEY (id);


--
-- Name: business_file business_file_storage_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.business_file
    ADD CONSTRAINT business_file_storage_key_key UNIQUE (storage_key);


--
-- Name: business_task business_task_automation_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.business_task
    ADD CONSTRAINT business_task_automation_key_key UNIQUE (automation_key);


--
-- Name: business_task business_task_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.business_task
    ADD CONSTRAINT business_task_pkey PRIMARY KEY (id);


--
-- Name: communication_contact_participant comm_contact_participant_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_contact_participant
    ADD CONSTRAINT comm_contact_participant_uniq UNIQUE (communication_id, customer_contact_id);


--
-- Name: communication_employee_participant comm_employee_participant_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_employee_participant
    ADD CONSTRAINT comm_employee_participant_uniq UNIQUE (communication_id, employee_id);


--
-- Name: communication_inquiry_link comm_inquiry_link_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_inquiry_link
    ADD CONSTRAINT comm_inquiry_link_uniq UNIQUE (communication_id, inquiry_id);


--
-- Name: communication_quotation_version_link comm_quote_version_link_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_quotation_version_link
    ADD CONSTRAINT comm_quote_version_link_uniq UNIQUE (communication_id, quotation_version_id);


--
-- Name: communication_sample_request_link comm_sample_request_link_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_sample_request_link
    ADD CONSTRAINT comm_sample_request_link_uniq UNIQUE (communication_id, sample_request_id);


--
-- Name: communication_contact_participant communication_contact_participant_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_contact_participant
    ADD CONSTRAINT communication_contact_participant_pkey PRIMARY KEY (id);


--
-- Name: communication_employee_participant communication_employee_participant_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_employee_participant
    ADD CONSTRAINT communication_employee_participant_pkey PRIMARY KEY (id);


--
-- Name: communication_file_link communication_file_link_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_file_link
    ADD CONSTRAINT communication_file_link_pkey PRIMARY KEY (id);


--
-- Name: communication_file_link communication_file_link_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_file_link
    ADD CONSTRAINT communication_file_link_uniq UNIQUE (communication_id, business_file_id);


--
-- Name: communication_inquiry_link communication_inquiry_link_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_inquiry_link
    ADD CONSTRAINT communication_inquiry_link_pkey PRIMARY KEY (id);


--
-- Name: communication_quotation_version_link communication_quotation_version_link_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_quotation_version_link
    ADD CONSTRAINT communication_quotation_version_link_pkey PRIMARY KEY (id);


--
-- Name: communication_sample_request_link communication_sample_request_link_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_sample_request_link
    ADD CONSTRAINT communication_sample_request_link_pkey PRIMARY KEY (id);


--
-- Name: communication_task_link communication_task_link_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_task_link
    ADD CONSTRAINT communication_task_link_pkey PRIMARY KEY (id);


--
-- Name: communication_task_link communication_task_link_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_task_link
    ADD CONSTRAINT communication_task_link_uniq UNIQUE (communication_id, business_task_id);


--
-- Name: customer_contact_role contact_role_no_overlap; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_contact_role
    ADD CONSTRAINT contact_role_no_overlap EXCLUDE USING gist (customer_contact_id WITH =, role_type WITH =, tstzrange(effective_from, effective_to, '[)'::text) WITH &&);


--
-- Name: customer_entity_address_usage cust_address_usage_no_overlap; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_entity_address_usage
    ADD CONSTRAINT cust_address_usage_no_overlap EXCLUDE USING gist (entity_address_id WITH =, usage_type WITH =, tstzrange(effective_from, effective_to, '[)'::text) WITH &&);


--
-- Name: customer_attention_review cust_attention_no_overlap; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_attention_review
    ADD CONSTRAINT cust_attention_no_overlap EXCLUDE USING gist (customer_account_id WITH =, tstzrange(effective_from, effective_to, '[)'::text) WITH &&);


--
-- Name: customer_duplicate_candidate cust_dup_candidate_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_duplicate_candidate
    ADD CONSTRAINT cust_dup_candidate_uniq UNIQUE (duplicate_case_id, customer_account_id);


--
-- Name: customer_entity_address cust_entity_address_code_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_entity_address
    ADD CONSTRAINT cust_entity_address_code_uniq UNIQUE (transaction_entity_id, address_code);


--
-- Name: customer_transaction_entity_role cust_entity_role_no_overlap; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_transaction_entity_role
    ADD CONSTRAINT cust_entity_role_no_overlap EXCLUDE USING gist (transaction_entity_id WITH =, role_type WITH =, tstzrange(effective_from, effective_to, '[)'::text) WITH &&);


--
-- Name: customer_data_access_grant cust_grant_no_overlap; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_data_access_grant
    ADD CONSTRAINT cust_grant_no_overlap EXCLUDE USING gist (employee_id WITH =, customer_account_id WITH =, permission_id WITH =, tstzrange(effective_from, effective_to, '[)'::text) WITH &&);


--
-- Name: customer_merge_change cust_merge_change_seq_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_merge_change
    ADD CONSTRAINT cust_merge_change_seq_uniq UNIQUE (merge_operation_id, sequence_number);


--
-- Name: customer_merge_member cust_merge_member_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_merge_member
    ADD CONSTRAINT cust_merge_member_uniq UNIQUE (merge_operation_id, customer_account_id);


--
-- Name: customer_account customer_account_account_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_account
    ADD CONSTRAINT customer_account_account_code_key UNIQUE (account_code);


--
-- Name: customer_account customer_account_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_account
    ADD CONSTRAINT customer_account_pkey PRIMARY KEY (id);


--
-- Name: customer_assignment customer_assignment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_assignment
    ADD CONSTRAINT customer_assignment_pkey PRIMARY KEY (id);


--
-- Name: customer_attention_review customer_attention_review_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_attention_review
    ADD CONSTRAINT customer_attention_review_pkey PRIMARY KEY (id);


--
-- Name: customer_communication customer_communication_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_communication
    ADD CONSTRAINT customer_communication_pkey PRIMARY KEY (id);


--
-- Name: customer_contact_method customer_contact_method_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_contact_method
    ADD CONSTRAINT customer_contact_method_pkey PRIMARY KEY (id);


--
-- Name: customer_contact customer_contact_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_contact
    ADD CONSTRAINT customer_contact_pkey PRIMARY KEY (id);


--
-- Name: customer_contact_role customer_contact_role_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_contact_role
    ADD CONSTRAINT customer_contact_role_pkey PRIMARY KEY (id);


--
-- Name: customer_data_access_grant customer_data_access_grant_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_data_access_grant
    ADD CONSTRAINT customer_data_access_grant_pkey PRIMARY KEY (id);


--
-- Name: customer_duplicate_candidate customer_duplicate_candidate_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_duplicate_candidate
    ADD CONSTRAINT customer_duplicate_candidate_pkey PRIMARY KEY (id);


--
-- Name: customer_duplicate_case customer_duplicate_case_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_duplicate_case
    ADD CONSTRAINT customer_duplicate_case_pkey PRIMARY KEY (id);


--
-- Name: customer_entity_address customer_entity_address_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_entity_address
    ADD CONSTRAINT customer_entity_address_pkey PRIMARY KEY (id);


--
-- Name: customer_entity_address_usage customer_entity_address_usage_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_entity_address_usage
    ADD CONSTRAINT customer_entity_address_usage_pkey PRIMARY KEY (id);


--
-- Name: customer_file_link customer_file_link_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_file_link
    ADD CONSTRAINT customer_file_link_pkey PRIMARY KEY (id);


--
-- Name: customer_file_link customer_file_link_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_file_link
    ADD CONSTRAINT customer_file_link_uniq UNIQUE (customer_account_id, business_file_id);


--
-- Name: customer_historical_transaction_confirmation customer_historical_transaction_confirmation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_historical_transaction_confirmation
    ADD CONSTRAINT customer_historical_transaction_confirmation_pkey PRIMARY KEY (id);


--
-- Name: customer_merge_change customer_merge_change_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_merge_change
    ADD CONSTRAINT customer_merge_change_pkey PRIMARY KEY (id);


--
-- Name: customer_merge_member customer_merge_member_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_merge_member
    ADD CONSTRAINT customer_merge_member_pkey PRIMARY KEY (id);


--
-- Name: customer_merge_operation customer_merge_operation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_merge_operation
    ADD CONSTRAINT customer_merge_operation_pkey PRIMARY KEY (id);


--
-- Name: customer_assignment customer_primary_owner_no_overlap; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_assignment
    ADD CONSTRAINT customer_primary_owner_no_overlap EXCLUDE USING gist (customer_account_id WITH =, tstzrange(effective_from, effective_to, '[)'::text) WITH &&) WHERE (((assignment_role)::text = 'PRIMARY_OWNER'::text));


--
-- Name: customer_task_link customer_task_link_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_task_link
    ADD CONSTRAINT customer_task_link_pkey PRIMARY KEY (id);


--
-- Name: customer_task_link customer_task_link_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_task_link
    ADD CONSTRAINT customer_task_link_uniq UNIQUE (customer_account_id, business_task_id);


--
-- Name: customer_timeline_event customer_timeline_event_event_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_timeline_event
    ADD CONSTRAINT customer_timeline_event_event_key_key UNIQUE (event_key);


--
-- Name: customer_timeline_event customer_timeline_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_timeline_event
    ADD CONSTRAINT customer_timeline_event_pkey PRIMARY KEY (id);


--
-- Name: customer_transaction_entity customer_transaction_entity_entity_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_transaction_entity
    ADD CONSTRAINT customer_transaction_entity_entity_code_key UNIQUE (entity_code);


--
-- Name: customer_transaction_entity customer_transaction_entity_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_transaction_entity
    ADD CONSTRAINT customer_transaction_entity_pkey PRIMARY KEY (id);


--
-- Name: customer_transaction_entity_role customer_transaction_entity_role_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_transaction_entity_role
    ADD CONSTRAINT customer_transaction_entity_role_pkey PRIMARY KEY (id);


--
-- Name: customer_transfer_request customer_transfer_request_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_transfer_request
    ADD CONSTRAINT customer_transfer_request_pkey PRIMARY KEY (id);


--
-- Name: django_admin_log django_admin_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_admin_log
    ADD CONSTRAINT django_admin_log_pkey PRIMARY KEY (id);


--
-- Name: django_content_type django_content_type_app_label_model_76bd3d3b_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_content_type
    ADD CONSTRAINT django_content_type_app_label_model_76bd3d3b_uniq UNIQUE (app_label, model);


--
-- Name: django_content_type django_content_type_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_content_type
    ADD CONSTRAINT django_content_type_pkey PRIMARY KEY (id);


--
-- Name: django_migrations django_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_migrations
    ADD CONSTRAINT django_migrations_pkey PRIMARY KEY (id);


--
-- Name: django_session django_session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_session
    ADD CONSTRAINT django_session_pkey PRIMARY KEY (session_key);


--
-- Name: employee_organization_assignment emp_org_no_overlap; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee_organization_assignment
    ADD CONSTRAINT emp_org_no_overlap EXCLUDE USING gist (employee_id WITH =, organization_unit_id WITH =, tstzrange(effective_from, effective_to, '[)'::text) WITH &&);


--
-- Name: employee_organization_assignment emp_primary_org_no_overlap; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee_organization_assignment
    ADD CONSTRAINT emp_primary_org_no_overlap EXCLUDE USING gist (employee_id WITH =, tstzrange(effective_from, effective_to, '[)'::text) WITH &&) WHERE (is_primary);


--
-- Name: employee_role_assignment emp_role_no_overlap; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee_role_assignment
    ADD CONSTRAINT emp_role_no_overlap EXCLUDE USING gist (employee_id WITH =, role_profile_id WITH =, tstzrange(effective_from, effective_to, '[)'::text) WITH &&);


--
-- Name: employee employee_employee_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee
    ADD CONSTRAINT employee_employee_code_key UNIQUE (employee_code);


--
-- Name: employee_organization_assignment employee_organization_assignment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee_organization_assignment
    ADD CONSTRAINT employee_organization_assignment_pkey PRIMARY KEY (id);


--
-- Name: employee employee_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee
    ADD CONSTRAINT employee_pkey PRIMARY KEY (id);


--
-- Name: employee_role_assignment employee_role_assignment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee_role_assignment
    ADD CONSTRAINT employee_role_assignment_pkey PRIMARY KEY (id);


--
-- Name: employee employee_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee
    ADD CONSTRAINT employee_user_id_key UNIQUE (user_id);


--
-- Name: import_batch import_batch_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_batch
    ADD CONSTRAINT import_batch_pkey PRIMARY KEY (id);


--
-- Name: import_record import_record_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_record
    ADD CONSTRAINT import_record_pkey PRIMARY KEY (id);


--
-- Name: import_record import_record_row_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_record
    ADD CONSTRAINT import_record_row_uniq UNIQUE (import_batch_id, row_number);


--
-- Name: inquiry_file_link inquiry_file_link_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inquiry_file_link
    ADD CONSTRAINT inquiry_file_link_pkey PRIMARY KEY (id);


--
-- Name: inquiry_file_link inquiry_file_link_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inquiry_file_link
    ADD CONSTRAINT inquiry_file_link_uniq UNIQUE (inquiry_id, business_file_id);


--
-- Name: inquiry inquiry_inquiry_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inquiry
    ADD CONSTRAINT inquiry_inquiry_number_key UNIQUE (inquiry_number);


--
-- Name: inquiry_item inquiry_item_line_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inquiry_item
    ADD CONSTRAINT inquiry_item_line_uniq UNIQUE (inquiry_id, line_number);


--
-- Name: inquiry_item inquiry_item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inquiry_item
    ADD CONSTRAINT inquiry_item_pkey PRIMARY KEY (id);


--
-- Name: inquiry inquiry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inquiry
    ADD CONSTRAINT inquiry_pkey PRIMARY KEY (id);


--
-- Name: inquiry_sla_link inquiry_sla_link_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inquiry_sla_link
    ADD CONSTRAINT inquiry_sla_link_pkey PRIMARY KEY (id);


--
-- Name: inquiry_sla_link inquiry_sla_link_sla_tracking_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inquiry_sla_link
    ADD CONSTRAINT inquiry_sla_link_sla_tracking_id_key UNIQUE (sla_tracking_id);


--
-- Name: inquiry_task_link inquiry_task_link_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inquiry_task_link
    ADD CONSTRAINT inquiry_task_link_pkey PRIMARY KEY (id);


--
-- Name: inquiry_task_link inquiry_task_link_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inquiry_task_link
    ADD CONSTRAINT inquiry_task_link_uniq UNIQUE (inquiry_id, business_task_id);


--
-- Name: organization_unit organization_unit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_unit
    ADD CONSTRAINT organization_unit_pkey PRIMARY KEY (id);


--
-- Name: organization_unit organization_unit_unit_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_unit
    ADD CONSTRAINT organization_unit_unit_code_key UNIQUE (unit_code);


--
-- Name: quotation_dispatch_record quotation_dispatch_record_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_dispatch_record
    ADD CONSTRAINT quotation_dispatch_record_pkey PRIMARY KEY (id);


--
-- Name: quotation_document quotation_document_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_document
    ADD CONSTRAINT quotation_document_pkey PRIMARY KEY (id);


--
-- Name: quotation_file_link quotation_file_link_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_file_link
    ADD CONSTRAINT quotation_file_link_pkey PRIMARY KEY (id);


--
-- Name: quotation_file_link quotation_file_link_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_file_link
    ADD CONSTRAINT quotation_file_link_uniq UNIQUE (quotation_version_id, business_file_id);


--
-- Name: quotation_line quotation_line_number_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_line
    ADD CONSTRAINT quotation_line_number_uniq UNIQUE (quotation_version_id, line_number);


--
-- Name: quotation_line quotation_line_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_line
    ADD CONSTRAINT quotation_line_pkey PRIMARY KEY (id);


--
-- Name: quotation quotation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation
    ADD CONSTRAINT quotation_pkey PRIMARY KEY (id);


--
-- Name: quotation_quantity_tier quotation_quantity_tier_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_quantity_tier
    ADD CONSTRAINT quotation_quantity_tier_pkey PRIMARY KEY (id);


--
-- Name: quotation quotation_quotation_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation
    ADD CONSTRAINT quotation_quotation_number_key UNIQUE (quotation_number);


--
-- Name: quotation_version_task_link quotation_task_link_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_version_task_link
    ADD CONSTRAINT quotation_task_link_uniq UNIQUE (quotation_version_id, business_task_id);


--
-- Name: quotation_template quotation_template_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_template
    ADD CONSTRAINT quotation_template_pkey PRIMARY KEY (id);


--
-- Name: quotation_template quotation_template_template_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_template
    ADD CONSTRAINT quotation_template_template_code_key UNIQUE (template_code);


--
-- Name: quotation_version_approval_link quotation_version_approval_link_approval_request_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_version_approval_link
    ADD CONSTRAINT quotation_version_approval_link_approval_request_id_key UNIQUE (approval_request_id);


--
-- Name: quotation_version_approval_link quotation_version_approval_link_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_version_approval_link
    ADD CONSTRAINT quotation_version_approval_link_pkey PRIMARY KEY (id);


--
-- Name: quotation_version quotation_version_number_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_version
    ADD CONSTRAINT quotation_version_number_uniq UNIQUE (quotation_id, version_number);


--
-- Name: quotation_version quotation_version_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_version
    ADD CONSTRAINT quotation_version_pkey PRIMARY KEY (id);


--
-- Name: quotation_version_sla_link quotation_version_sla_link_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_version_sla_link
    ADD CONSTRAINT quotation_version_sla_link_pkey PRIMARY KEY (id);


--
-- Name: quotation_version_sla_link quotation_version_sla_link_sla_tracking_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_version_sla_link
    ADD CONSTRAINT quotation_version_sla_link_sla_tracking_id_key UNIQUE (sla_tracking_id);


--
-- Name: quotation_version_task_link quotation_version_task_link_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_version_task_link
    ADD CONSTRAINT quotation_version_task_link_pkey PRIMARY KEY (id);


--
-- Name: quotation_quantity_tier quote_tier_no_overlap; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_quantity_tier
    ADD CONSTRAINT quote_tier_no_overlap EXCLUDE USING gist (quotation_line_id WITH =, numrange(min_quantity, max_quantity, '[)'::text) WITH &&);


--
-- Name: reference_dictionary ref_dict_category_item_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reference_dictionary
    ADD CONSTRAINT ref_dict_category_item_uniq UNIQUE (category_code, item_code);


--
-- Name: reference_dictionary reference_dictionary_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reference_dictionary
    ADD CONSTRAINT reference_dictionary_pkey PRIMARY KEY (id);


--
-- Name: role_profile role_profile_auth_group_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_profile
    ADD CONSTRAINT role_profile_auth_group_id_key UNIQUE (auth_group_id);


--
-- Name: role_profile role_profile_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_profile
    ADD CONSTRAINT role_profile_pkey PRIMARY KEY (id);


--
-- Name: role_profile role_profile_role_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_profile
    ADD CONSTRAINT role_profile_role_code_key UNIQUE (role_code);


--
-- Name: sample_approval_link sample_approval_link_approval_request_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_approval_link
    ADD CONSTRAINT sample_approval_link_approval_request_id_key UNIQUE (approval_request_id);


--
-- Name: sample_approval_link sample_approval_link_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_approval_link
    ADD CONSTRAINT sample_approval_link_pkey PRIMARY KEY (id);


--
-- Name: sample_fee_record sample_fee_record_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_fee_record
    ADD CONSTRAINT sample_fee_record_pkey PRIMARY KEY (id);


--
-- Name: sample_feedback sample_feedback_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_feedback
    ADD CONSTRAINT sample_feedback_pkey PRIMARY KEY (id);


--
-- Name: sample_file_link sample_file_link_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_file_link
    ADD CONSTRAINT sample_file_link_pkey PRIMARY KEY (id);


--
-- Name: sample_file_link sample_file_link_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_file_link
    ADD CONSTRAINT sample_file_link_uniq UNIQUE (sample_request_id, business_file_id);


--
-- Name: sample_item sample_item_line_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_item
    ADD CONSTRAINT sample_item_line_uniq UNIQUE (sample_request_id, line_number);


--
-- Name: sample_item sample_item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_item
    ADD CONSTRAINT sample_item_pkey PRIMARY KEY (id);


--
-- Name: sample_request sample_request_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_request
    ADD CONSTRAINT sample_request_pkey PRIMARY KEY (id);


--
-- Name: sample_request sample_request_request_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_request
    ADD CONSTRAINT sample_request_request_number_key UNIQUE (request_number);


--
-- Name: sample_shipment_item sample_shipment_item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_shipment_item
    ADD CONSTRAINT sample_shipment_item_pkey PRIMARY KEY (id);


--
-- Name: sample_shipment_item sample_shipment_item_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_shipment_item
    ADD CONSTRAINT sample_shipment_item_uniq UNIQUE (sample_shipment_id, sample_item_id);


--
-- Name: sample_shipment sample_shipment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_shipment
    ADD CONSTRAINT sample_shipment_pkey PRIMARY KEY (id);


--
-- Name: sample_sla_link sample_sla_link_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_sla_link
    ADD CONSTRAINT sample_sla_link_pkey PRIMARY KEY (id);


--
-- Name: sample_sla_link sample_sla_link_sla_tracking_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_sla_link
    ADD CONSTRAINT sample_sla_link_sla_tracking_id_key UNIQUE (sla_tracking_id);


--
-- Name: sample_task_link sample_task_link_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_task_link
    ADD CONSTRAINT sample_task_link_pkey PRIMARY KEY (id);


--
-- Name: sample_task_link sample_task_link_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_task_link
    ADD CONSTRAINT sample_task_link_uniq UNIQUE (sample_request_id, business_task_id);


--
-- Name: saved_view saved_view_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.saved_view
    ADD CONSTRAINT saved_view_pkey PRIMARY KEY (id);


--
-- Name: sla_policy sla_policy_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sla_policy
    ADD CONSTRAINT sla_policy_pkey PRIMARY KEY (id);


--
-- Name: sla_policy sla_policy_policy_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sla_policy
    ADD CONSTRAINT sla_policy_policy_code_key UNIQUE (policy_code);


--
-- Name: sla_tracking sla_tracking_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sla_tracking
    ADD CONSTRAINT sla_tracking_pkey PRIMARY KEY (id);


--
-- Name: approval_pending_inbox_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX approval_pending_inbox_idx ON public.approval_request USING btree (current_approver_employee_id, submitted_at, id) WHERE ((status)::text = 'PENDING'::text);


--
-- Name: approval_request_current_approver_employee_id_0adc7768; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX approval_request_current_approver_employee_id_0adc7768 ON public.approval_request USING btree (current_approver_employee_id);


--
-- Name: approval_request_requested_by_employee_id_edf269a6; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX approval_request_requested_by_employee_id_edf269a6 ON public.approval_request USING btree (requested_by_employee_id);


--
-- Name: audit_actor_history_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_actor_history_idx ON public.audit_log USING btree (actor_employee_id, occurred_at DESC, id DESC);


--
-- Name: audit_context_history_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_context_history_idx ON public.audit_log USING btree (context_type, context_id, occurred_at DESC, id DESC);


--
-- Name: audit_log_actor_employee_id_cfc825de; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_log_actor_employee_id_cfc825de ON public.audit_log USING btree (actor_employee_id);


--
-- Name: audit_object_history_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_object_history_idx ON public.audit_log USING btree (object_type, object_id, occurred_at DESC, id DESC);


--
-- Name: auth_group_name_a6ea08ec_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_group_name_a6ea08ec_like ON public.auth_group USING btree (name varchar_pattern_ops);


--
-- Name: auth_group_permissions_group_id_b120cbf9; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_group_permissions_group_id_b120cbf9 ON public.auth_group_permissions USING btree (group_id);


--
-- Name: auth_group_permissions_permission_id_84c5c92e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_group_permissions_permission_id_84c5c92e ON public.auth_group_permissions USING btree (permission_id);


--
-- Name: auth_permission_content_type_id_2f476e4b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_permission_content_type_id_2f476e4b ON public.auth_permission USING btree (content_type_id);


--
-- Name: auth_user_groups_group_id_97559544; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_user_groups_group_id_97559544 ON public.auth_user_groups USING btree (group_id);


--
-- Name: auth_user_groups_user_id_6a12ed8b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_user_groups_user_id_6a12ed8b ON public.auth_user_groups USING btree (user_id);


--
-- Name: auth_user_user_permissions_permission_id_1fbb5f2c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_user_user_permissions_permission_id_1fbb5f2c ON public.auth_user_user_permissions USING btree (permission_id);


--
-- Name: auth_user_user_permissions_user_id_a95ead1b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_user_user_permissions_user_id_a95ead1b ON public.auth_user_user_permissions USING btree (user_id);


--
-- Name: auth_user_username_6821ab7c_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_user_username_6821ab7c_like ON public.auth_user USING btree (username varchar_pattern_ops);


--
-- Name: automation_execution_idempotency_key_4e28d65e_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX automation_execution_idempotency_key_4e28d65e_like ON public.automation_execution USING btree (idempotency_key varchar_pattern_ops);


--
-- Name: automation_ready_retry_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX automation_ready_retry_idx ON public.automation_execution USING btree (status, next_retry_at, id) WHERE ((status)::text = ANY ((ARRAY['PENDING'::character varying, 'RETRY'::character varying])::text[]));


--
-- Name: business_file_archived_by_employee_id_bf8b1e3a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX business_file_archived_by_employee_id_bf8b1e3a ON public.business_file USING btree (archived_by_employee_id);


--
-- Name: business_file_hash_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX business_file_hash_idx ON public.business_file USING btree (content_hash) WHERE (NOT ((content_hash)::text = ''::text));


--
-- Name: business_file_scan_queue_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX business_file_scan_queue_idx ON public.business_file USING btree (scan_status, created_at, id) WHERE ((scan_status)::text = 'PENDING'::text);


--
-- Name: business_file_storage_key_b5bd9158_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX business_file_storage_key_b5bd9158_like ON public.business_file USING btree (storage_key varchar_pattern_ops);


--
-- Name: business_file_uploaded_by_employee_id_edfa1024; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX business_file_uploaded_by_employee_id_edfa1024 ON public.business_file USING btree (uploaded_by_employee_id);


--
-- Name: business_task_archived_by_employee_id_4dcc5ec7; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX business_task_archived_by_employee_id_4dcc5ec7 ON public.business_task USING btree (archived_by_employee_id);


--
-- Name: business_task_assignee_employee_id_7278676f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX business_task_assignee_employee_id_7278676f ON public.business_task USING btree (assignee_employee_id);


--
-- Name: business_task_automation_key_1d534ba6_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX business_task_automation_key_1d534ba6_like ON public.business_task USING btree (automation_key varchar_pattern_ops);


--
-- Name: business_task_created_by_employee_id_edca13ae; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX business_task_created_by_employee_id_edca13ae ON public.business_task USING btree (created_by_employee_id);


--
-- Name: comm_contact_lookup_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX comm_contact_lookup_idx ON public.communication_contact_participant USING btree (customer_contact_id, communication_id);


--
-- Name: comm_employee_lookup_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX comm_employee_lookup_idx ON public.communication_employee_participant USING btree (employee_id, communication_id);


--
-- Name: comm_inquiry_lookup_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX comm_inquiry_lookup_idx ON public.communication_inquiry_link USING btree (inquiry_id, communication_id);


--
-- Name: comm_quote_lookup_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX comm_quote_lookup_idx ON public.communication_quotation_version_link USING btree (quotation_version_id, communication_id);


--
-- Name: comm_sample_lookup_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX comm_sample_lookup_idx ON public.communication_sample_request_link USING btree (sample_request_id, communication_id);


--
-- Name: communication_contact_participant_communication_id_c6edb269; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX communication_contact_participant_communication_id_c6edb269 ON public.communication_contact_participant USING btree (communication_id);


--
-- Name: communication_contact_participant_customer_contact_id_c6ee9af5; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX communication_contact_participant_customer_contact_id_c6ee9af5 ON public.communication_contact_participant USING btree (customer_contact_id);


--
-- Name: communication_creator_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX communication_creator_idx ON public.customer_communication USING btree (created_by_employee_id, occurred_at DESC, id DESC) WHERE (archived_at IS NULL);


--
-- Name: communication_customer_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX communication_customer_idx ON public.customer_communication USING btree (customer_account_id, occurred_at DESC, id DESC) WHERE (archived_at IS NULL);


--
-- Name: communication_employee_participant_communication_id_587e4354; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX communication_employee_participant_communication_id_587e4354 ON public.communication_employee_participant USING btree (communication_id);


--
-- Name: communication_employee_participant_employee_id_1079d64e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX communication_employee_participant_employee_id_1079d64e ON public.communication_employee_participant USING btree (employee_id);


--
-- Name: communication_external_source_uniq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX communication_external_source_uniq ON public.customer_communication USING btree (source_system, external_id) WHERE ((NOT ((source_system)::text = ''::text)) AND (NOT ((external_id)::text = ''::text)));


--
-- Name: communication_file_link_business_file_id_bd9f280c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX communication_file_link_business_file_id_bd9f280c ON public.communication_file_link USING btree (business_file_id);


--
-- Name: communication_file_link_communication_id_67ea505c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX communication_file_link_communication_id_67ea505c ON public.communication_file_link USING btree (communication_id);


--
-- Name: communication_inquiry_link_communication_id_ef83aa86; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX communication_inquiry_link_communication_id_ef83aa86 ON public.communication_inquiry_link USING btree (communication_id);


--
-- Name: communication_inquiry_link_inquiry_id_0614c444; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX communication_inquiry_link_inquiry_id_0614c444 ON public.communication_inquiry_link USING btree (inquiry_id);


--
-- Name: communication_quotation_ve_quotation_version_id_508c9377; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX communication_quotation_ve_quotation_version_id_508c9377 ON public.communication_quotation_version_link USING btree (quotation_version_id);


--
-- Name: communication_quotation_version_link_communication_id_bb222218; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX communication_quotation_version_link_communication_id_bb222218 ON public.communication_quotation_version_link USING btree (communication_id);


--
-- Name: communication_sample_request_link_communication_id_85f01af4; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX communication_sample_request_link_communication_id_85f01af4 ON public.communication_sample_request_link USING btree (communication_id);


--
-- Name: communication_sample_request_link_sample_request_id_0b0d2f5d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX communication_sample_request_link_sample_request_id_0b0d2f5d ON public.communication_sample_request_link USING btree (sample_request_id);


--
-- Name: communication_task_link_business_task_id_22a779fe; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX communication_task_link_business_task_id_22a779fe ON public.communication_task_link USING btree (business_task_id);


--
-- Name: communication_task_link_communication_id_3f635540; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX communication_task_link_communication_id_3f635540 ON public.communication_task_link USING btree (communication_id);


--
-- Name: communication_task_primary_uniq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX communication_task_primary_uniq ON public.communication_task_link USING btree (business_task_id) WHERE is_primary_source;


--
-- Name: contact_account_active_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX contact_account_active_idx ON public.customer_contact USING btree (customer_account_id, display_name, id) WHERE (archived_at IS NULL);


--
-- Name: contact_entity_active_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX contact_entity_active_idx ON public.customer_contact USING btree (transaction_entity_id, display_name, id) WHERE ((archived_at IS NULL) AND (transaction_entity_id IS NOT NULL));


--
-- Name: contact_method_lookup_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX contact_method_lookup_idx ON public.customer_contact_method USING btree (method_type, normalized_value) WHERE (archived_at IS NULL);


--
-- Name: contact_method_preferred_uniq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX contact_method_preferred_uniq ON public.customer_contact_method USING btree (customer_contact_id, method_type) WHERE ((archived_at IS NULL) AND is_preferred);


--
-- Name: contact_method_primary_uniq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX contact_method_primary_uniq ON public.customer_contact_method USING btree (customer_contact_id, method_type) WHERE ((archived_at IS NULL) AND is_primary);


--
-- Name: contact_name_trgm_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX contact_name_trgm_idx ON public.customer_contact USING gin (display_name public.gin_trgm_ops);


--
-- Name: contact_role_history_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX contact_role_history_idx ON public.customer_contact_role USING btree (customer_contact_id, effective_from DESC, id DESC);


--
-- Name: cust_address_entity_active_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cust_address_entity_active_idx ON public.customer_entity_address USING btree (transaction_entity_id, address_code, id) WHERE (archived_at IS NULL);


--
-- Name: cust_assign_current_emp_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cust_assign_current_emp_idx ON public.customer_assignment USING btree (employee_id, assignment_role, customer_account_id) WHERE (effective_to IS NULL);


--
-- Name: cust_assign_history_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cust_assign_history_idx ON public.customer_assignment USING btree (customer_account_id, effective_from DESC, id DESC);


--
-- Name: cust_attention_current_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cust_attention_current_idx ON public.customer_attention_review USING btree (attention_level_item_id, customer_account_id) WHERE (effective_to IS NULL);


--
-- Name: cust_attention_history_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cust_attention_history_idx ON public.customer_attention_review USING btree (customer_account_id, effective_from DESC, id DESC);


--
-- Name: cust_dup_account_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cust_dup_account_idx ON public.customer_duplicate_candidate USING btree (customer_account_id, created_at DESC, id DESC);


--
-- Name: cust_dup_case_open_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cust_dup_case_open_idx ON public.customer_duplicate_case USING btree (status, created_at, id) WHERE ((status)::text = ANY ((ARRAY['OPEN'::character varying, 'REVIEWING'::character varying])::text[]));


--
-- Name: cust_dup_case_score_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cust_dup_case_score_idx ON public.customer_duplicate_candidate USING btree (duplicate_case_id, confidence_score DESC, id DESC);


--
-- Name: cust_dup_reviewer_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cust_dup_reviewer_idx ON public.customer_duplicate_case USING btree (reviewer_employee_id, status, created_at, id);


--
-- Name: cust_entity_account_active_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cust_entity_account_active_idx ON public.customer_transaction_entity USING btree (customer_account_id, legal_name, id) WHERE (archived_at IS NULL);


--
-- Name: cust_entity_name_trgm_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cust_entity_name_trgm_idx ON public.customer_transaction_entity USING gin (legal_name public.gin_trgm_ops);


--
-- Name: cust_entity_reg_lookup_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cust_entity_reg_lookup_idx ON public.customer_transaction_entity USING btree (registration_country_code, registration_number) WHERE ((NOT ((registration_number)::text = ''::text)) AND (archived_at IS NULL));


--
-- Name: cust_entity_tax_lookup_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cust_entity_tax_lookup_idx ON public.customer_transaction_entity USING btree (tax_country_code, tax_identifier) WHERE ((NOT ((tax_identifier)::text = ''::text)) AND (archived_at IS NULL));


--
-- Name: cust_grant_customer_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cust_grant_customer_idx ON public.customer_data_access_grant USING btree (customer_account_id, employee_id);


--
-- Name: cust_grant_employee_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cust_grant_employee_idx ON public.customer_data_access_grant USING btree (employee_id, permission_id, customer_account_id);


--
-- Name: cust_history_confirm_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cust_history_confirm_idx ON public.customer_historical_transaction_confirmation USING btree (customer_account_id, created_at DESC, id DESC);


--
-- Name: cust_history_confirm_queue_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cust_history_confirm_queue_idx ON public.customer_historical_transaction_confirmation USING btree (status, created_at, id) WHERE ((status)::text = 'PENDING'::text);


--
-- Name: cust_merge_account_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cust_merge_account_idx ON public.customer_merge_member USING btree (customer_account_id, created_at DESC, id DESC);


--
-- Name: cust_merge_case_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cust_merge_case_idx ON public.customer_merge_operation USING btree (duplicate_case_id, created_at DESC, id DESC);


--
-- Name: cust_merge_one_survivor_uniq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX cust_merge_one_survivor_uniq ON public.customer_merge_member USING btree (merge_operation_id) WHERE ((member_role)::text = 'SURVIVOR'::text);


--
-- Name: cust_transfer_history_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cust_transfer_history_idx ON public.customer_transfer_request USING btree (customer_account_id, submitted_at DESC, id DESC);


--
-- Name: cust_transfer_pending_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cust_transfer_pending_idx ON public.customer_transfer_request USING btree (status, submitted_at, id) WHERE ((status)::text = 'PENDING'::text);


--
-- Name: customer_account_account_code_065de23b_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_account_account_code_065de23b_like ON public.customer_account USING btree (account_code varchar_pattern_ops);


--
-- Name: customer_account_archived_by_employee_id_e9c5dbdf; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_account_archived_by_employee_id_e9c5dbdf ON public.customer_account USING btree (archived_by_employee_id);


--
-- Name: customer_assignment_assigned_by_employee_id_ecc3f689; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_assignment_assigned_by_employee_id_ecc3f689 ON public.customer_assignment USING btree (assigned_by_employee_id);


--
-- Name: customer_assignment_customer_account_id_83f569b2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_assignment_customer_account_id_83f569b2 ON public.customer_assignment USING btree (customer_account_id);


--
-- Name: customer_assignment_employee_id_c370c440; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_assignment_employee_id_c370c440 ON public.customer_assignment USING btree (employee_id);


--
-- Name: customer_attention_review_attention_level_item_id_48ccf133; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_attention_review_attention_level_item_id_48ccf133 ON public.customer_attention_review USING btree (attention_level_item_id);


--
-- Name: customer_attention_review_customer_account_id_2d6b266b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_attention_review_customer_account_id_2d6b266b ON public.customer_attention_review USING btree (customer_account_id);


--
-- Name: customer_attention_review_reviewed_by_employee_id_a3822f3e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_attention_review_reviewed_by_employee_id_a3822f3e ON public.customer_attention_review USING btree (reviewed_by_employee_id);


--
-- Name: customer_communication_archived_by_employee_id_4fda484c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_communication_archived_by_employee_id_4fda484c ON public.customer_communication USING btree (archived_by_employee_id);


--
-- Name: customer_communication_created_by_employee_id_6699ec01; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_communication_created_by_employee_id_6699ec01 ON public.customer_communication USING btree (created_by_employee_id);


--
-- Name: customer_communication_customer_account_id_ad398c9c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_communication_customer_account_id_ad398c9c ON public.customer_communication USING btree (customer_account_id);


--
-- Name: customer_contact_archived_by_employee_id_732bfa6e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_contact_archived_by_employee_id_732bfa6e ON public.customer_contact USING btree (archived_by_employee_id);


--
-- Name: customer_contact_customer_account_id_aba0cdd7; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_contact_customer_account_id_aba0cdd7 ON public.customer_contact USING btree (customer_account_id);


--
-- Name: customer_contact_method_archived_by_employee_id_abe7cbaa; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_contact_method_archived_by_employee_id_abe7cbaa ON public.customer_contact_method USING btree (archived_by_employee_id);


--
-- Name: customer_contact_method_customer_contact_id_1e76c682; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_contact_method_customer_contact_id_1e76c682 ON public.customer_contact_method USING btree (customer_contact_id);


--
-- Name: customer_contact_role_customer_contact_id_0e06cf8b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_contact_role_customer_contact_id_0e06cf8b ON public.customer_contact_role USING btree (customer_contact_id);


--
-- Name: customer_contact_source_contact_id_80f80a04; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_contact_source_contact_id_80f80a04 ON public.customer_contact USING btree (source_contact_id);


--
-- Name: customer_contact_transaction_entity_id_f02a47d9; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_contact_transaction_entity_id_f02a47d9 ON public.customer_contact USING btree (transaction_entity_id);


--
-- Name: customer_country_active_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_country_active_idx ON public.customer_account USING btree (primary_country_code, updated_at DESC, id DESC) WHERE (archived_at IS NULL);


--
-- Name: customer_created_active_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_created_active_idx ON public.customer_account USING btree (created_at DESC, id DESC) WHERE (archived_at IS NULL);


--
-- Name: customer_data_access_grant_customer_account_id_3d17feb1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_data_access_grant_customer_account_id_3d17feb1 ON public.customer_data_access_grant USING btree (customer_account_id);


--
-- Name: customer_data_access_grant_employee_id_ce3fa450; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_data_access_grant_employee_id_ce3fa450 ON public.customer_data_access_grant USING btree (employee_id);


--
-- Name: customer_data_access_grant_granted_by_employee_id_d1df79f9; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_data_access_grant_granted_by_employee_id_d1df79f9 ON public.customer_data_access_grant USING btree (granted_by_employee_id);


--
-- Name: customer_data_access_grant_permission_id_7e511200; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_data_access_grant_permission_id_7e511200 ON public.customer_data_access_grant USING btree (permission_id);


--
-- Name: customer_data_access_grant_revoked_by_employee_id_5e1b2a69; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_data_access_grant_revoked_by_employee_id_5e1b2a69 ON public.customer_data_access_grant USING btree (revoked_by_employee_id);


--
-- Name: customer_duplicate_candidate_customer_account_id_f2bbab56; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_duplicate_candidate_customer_account_id_f2bbab56 ON public.customer_duplicate_candidate USING btree (customer_account_id);


--
-- Name: customer_duplicate_candidate_duplicate_case_id_e28005df; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_duplicate_candidate_duplicate_case_id_e28005df ON public.customer_duplicate_candidate USING btree (duplicate_case_id);


--
-- Name: customer_duplicate_case_reviewer_employee_id_dc16922c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_duplicate_case_reviewer_employee_id_dc16922c ON public.customer_duplicate_case USING btree (reviewer_employee_id);


--
-- Name: customer_english_trgm_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_english_trgm_idx ON public.customer_account USING gin (english_name public.gin_trgm_ops);


--
-- Name: customer_entity_address_archived_by_employee_id_df272d5d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_entity_address_archived_by_employee_id_df272d5d ON public.customer_entity_address USING btree (archived_by_employee_id);


--
-- Name: customer_entity_address_transaction_entity_id_d1630a0d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_entity_address_transaction_entity_id_d1630a0d ON public.customer_entity_address USING btree (transaction_entity_id);


--
-- Name: customer_entity_address_usage_entity_address_id_06ea6f4a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_entity_address_usage_entity_address_id_06ea6f4a ON public.customer_entity_address_usage USING btree (entity_address_id);


--
-- Name: customer_external_source_uniq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX customer_external_source_uniq ON public.customer_account USING btree (source_system, external_id) WHERE ((NOT ((source_system)::text = ''::text)) AND (NOT ((external_id)::text = ''::text)));


--
-- Name: customer_file_link_business_file_id_846696e0; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_file_link_business_file_id_846696e0 ON public.customer_file_link USING btree (business_file_id);


--
-- Name: customer_file_link_customer_account_id_af14e4eb; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_file_link_customer_account_id_af14e4eb ON public.customer_file_link USING btree (customer_account_id);


--
-- Name: customer_historical_transa_confirmed_by_employee_id_609e0281; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_historical_transa_confirmed_by_employee_id_609e0281 ON public.customer_historical_transaction_confirmation USING btree (confirmed_by_employee_id);


--
-- Name: customer_historical_transa_customer_account_id_a14c19e5; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_historical_transa_customer_account_id_a14c19e5 ON public.customer_historical_transaction_confirmation USING btree (customer_account_id);


--
-- Name: customer_merge_change_merge_operation_id_d99df7ea; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_merge_change_merge_operation_id_d99df7ea ON public.customer_merge_change USING btree (merge_operation_id);


--
-- Name: customer_merge_member_customer_account_id_cfb19112; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_merge_member_customer_account_id_cfb19112 ON public.customer_merge_member USING btree (customer_account_id);


--
-- Name: customer_merge_member_merge_operation_id_7450a503; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_merge_member_merge_operation_id_7450a503 ON public.customer_merge_member USING btree (merge_operation_id);


--
-- Name: customer_merge_operation_duplicate_case_id_ccf89ae5; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_merge_operation_duplicate_case_id_ccf89ae5 ON public.customer_merge_operation USING btree (duplicate_case_id);


--
-- Name: customer_merge_operation_executed_by_employee_id_606dd1fa; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_merge_operation_executed_by_employee_id_606dd1fa ON public.customer_merge_operation USING btree (executed_by_employee_id);


--
-- Name: customer_name_trgm_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_name_trgm_idx ON public.customer_account USING gin (account_name public.gin_trgm_ops);


--
-- Name: customer_short_trgm_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_short_trgm_idx ON public.customer_account USING gin (short_name public.gin_trgm_ops);


--
-- Name: customer_stage_active_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_stage_active_idx ON public.customer_account USING btree (lifecycle_stage, updated_at DESC, id DESC) WHERE (archived_at IS NULL);


--
-- Name: customer_task_link_business_task_id_f4bd0194; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_task_link_business_task_id_f4bd0194 ON public.customer_task_link USING btree (business_task_id);


--
-- Name: customer_task_link_customer_account_id_29c2112e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_task_link_customer_account_id_29c2112e ON public.customer_task_link USING btree (customer_account_id);


--
-- Name: customer_task_primary_uniq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX customer_task_primary_uniq ON public.customer_task_link USING btree (business_task_id) WHERE is_primary_source;


--
-- Name: customer_timeline_event_customer_account_id_cf506f25; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_timeline_event_customer_account_id_cf506f25 ON public.customer_timeline_event USING btree (customer_account_id);


--
-- Name: customer_timeline_event_event_key_54763e08_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_timeline_event_event_key_54763e08_like ON public.customer_timeline_event USING btree (event_key varchar_pattern_ops);


--
-- Name: customer_transaction_entity_archived_by_employee_id_54120e98; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_transaction_entity_archived_by_employee_id_54120e98 ON public.customer_transaction_entity USING btree (archived_by_employee_id);


--
-- Name: customer_transaction_entity_customer_account_id_a617d899; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_transaction_entity_customer_account_id_a617d899 ON public.customer_transaction_entity USING btree (customer_account_id);


--
-- Name: customer_transaction_entity_entity_code_ac4451fa_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_transaction_entity_entity_code_ac4451fa_like ON public.customer_transaction_entity USING btree (entity_code varchar_pattern_ops);


--
-- Name: customer_transaction_entity_role_transaction_entity_id_5536377e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_transaction_entity_role_transaction_entity_id_5536377e ON public.customer_transaction_entity_role USING btree (transaction_entity_id);


--
-- Name: customer_transfer_request_customer_account_id_18719b53; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_transfer_request_customer_account_id_18719b53 ON public.customer_transfer_request USING btree (customer_account_id);


--
-- Name: customer_transfer_request_decided_by_employee_id_5c5ebaee; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_transfer_request_decided_by_employee_id_5c5ebaee ON public.customer_transfer_request USING btree (decided_by_employee_id);


--
-- Name: customer_transfer_request_from_employee_id_53f242cb; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_transfer_request_from_employee_id_53f242cb ON public.customer_transfer_request USING btree (from_employee_id);


--
-- Name: customer_transfer_request_requested_by_employee_id_62060bc0; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_transfer_request_requested_by_employee_id_62060bc0 ON public.customer_transfer_request USING btree (requested_by_employee_id);


--
-- Name: customer_transfer_request_to_employee_id_b45dd562; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX customer_transfer_request_to_employee_id_b45dd562 ON public.customer_transfer_request USING btree (to_employee_id);


--
-- Name: django_admin_log_content_type_id_c4bce8eb; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_admin_log_content_type_id_c4bce8eb ON public.django_admin_log USING btree (content_type_id);


--
-- Name: django_admin_log_user_id_c564eba6; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_admin_log_user_id_c564eba6 ON public.django_admin_log USING btree (user_id);


--
-- Name: django_session_expire_date_a5c62663; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_session_expire_date_a5c62663 ON public.django_session USING btree (expire_date);


--
-- Name: django_session_session_key_c0390e0f_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_session_session_key_c0390e0f_like ON public.django_session USING btree (session_key varchar_pattern_ops);


--
-- Name: emp_org_current_unit_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX emp_org_current_unit_idx ON public.employee_organization_assignment USING btree (organization_unit_id, employee_id) WHERE (effective_to IS NULL);


--
-- Name: emp_org_history_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX emp_org_history_idx ON public.employee_organization_assignment USING btree (employee_id, effective_from DESC, id DESC);


--
-- Name: emp_role_current_emp_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX emp_role_current_emp_idx ON public.employee_role_assignment USING btree (employee_id, role_profile_id) WHERE (effective_to IS NULL);


--
-- Name: emp_role_current_role_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX emp_role_current_role_idx ON public.employee_role_assignment USING btree (role_profile_id, employee_id) WHERE (effective_to IS NULL);


--
-- Name: employee_archived_by_employee_id_c2520dab; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX employee_archived_by_employee_id_c2520dab ON public.employee USING btree (archived_by_employee_id);


--
-- Name: employee_employee_code_266cb541_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX employee_employee_code_266cb541_like ON public.employee USING btree (employee_code varchar_pattern_ops);


--
-- Name: employee_organization_assi_assigned_by_employee_id_ab17938c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX employee_organization_assi_assigned_by_employee_id_ab17938c ON public.employee_organization_assignment USING btree (assigned_by_employee_id);


--
-- Name: employee_organization_assignment_employee_id_5e606490; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX employee_organization_assignment_employee_id_5e606490 ON public.employee_organization_assignment USING btree (employee_id);


--
-- Name: employee_organization_assignment_organization_unit_id_9012096f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX employee_organization_assignment_organization_unit_id_9012096f ON public.employee_organization_assignment USING btree (organization_unit_id);


--
-- Name: employee_role_assignment_assigned_by_employee_id_801ccc70; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX employee_role_assignment_assigned_by_employee_id_801ccc70 ON public.employee_role_assignment USING btree (assigned_by_employee_id);


--
-- Name: employee_role_assignment_employee_id_eb614ca7; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX employee_role_assignment_employee_id_eb614ca7 ON public.employee_role_assignment USING btree (employee_id);


--
-- Name: employee_role_assignment_role_profile_id_d7376146; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX employee_role_assignment_role_profile_id_d7376146 ON public.employee_role_assignment USING btree (role_profile_id);


--
-- Name: import_batch_created_by_employee_id_441d15e7; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX import_batch_created_by_employee_id_441d15e7 ON public.import_batch USING btree (created_by_employee_id);


--
-- Name: import_batch_source_file_id_a90307e5; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX import_batch_source_file_id_a90307e5 ON public.import_batch USING btree (source_file_id);


--
-- Name: import_batch_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX import_batch_status_idx ON public.import_batch USING btree (status, created_at DESC, id DESC);


--
-- Name: import_record_batch_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX import_record_batch_status_idx ON public.import_record USING btree (import_batch_id, status, row_number);


--
-- Name: import_record_import_batch_id_0f1852be; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX import_record_import_batch_id_0f1852be ON public.import_record USING btree (import_batch_id);


--
-- Name: import_record_target_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX import_record_target_idx ON public.import_record USING btree (target_type, target_id) WHERE ((NOT ((target_type)::text = ''::text)) AND (target_id IS NOT NULL));


--
-- Name: inquiry_archived_by_employee_id_3c9f062f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX inquiry_archived_by_employee_id_3c9f062f ON public.inquiry USING btree (archived_by_employee_id);


--
-- Name: inquiry_contact_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX inquiry_contact_idx ON public.inquiry USING btree (customer_contact_id, received_at DESC, id DESC) WHERE ((archived_at IS NULL) AND (customer_contact_id IS NOT NULL));


--
-- Name: inquiry_customer_account_id_4643474e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX inquiry_customer_account_id_4643474e ON public.inquiry USING btree (customer_account_id);


--
-- Name: inquiry_customer_contact_id_7f3aba57; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX inquiry_customer_contact_id_7f3aba57 ON public.inquiry USING btree (customer_contact_id);


--
-- Name: inquiry_customer_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX inquiry_customer_idx ON public.inquiry USING btree (customer_account_id, received_at DESC, id DESC) WHERE (archived_at IS NULL);


--
-- Name: inquiry_entity_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX inquiry_entity_idx ON public.inquiry USING btree (transaction_entity_id, received_at DESC, id DESC) WHERE ((archived_at IS NULL) AND (transaction_entity_id IS NOT NULL));


--
-- Name: inquiry_external_source_uniq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX inquiry_external_source_uniq ON public.inquiry USING btree (source_system, external_id) WHERE ((NOT ((source_system)::text = ''::text)) AND (NOT ((external_id)::text = ''::text)));


--
-- Name: inquiry_file_link_business_file_id_bdca94b4; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX inquiry_file_link_business_file_id_bdca94b4 ON public.inquiry_file_link USING btree (business_file_id);


--
-- Name: inquiry_file_link_inquiry_id_94c95015; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX inquiry_file_link_inquiry_id_94c95015 ON public.inquiry_file_link USING btree (inquiry_id);


--
-- Name: inquiry_inquiry_number_ae9d9279_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX inquiry_inquiry_number_ae9d9279_like ON public.inquiry USING btree (inquiry_number varchar_pattern_ops);


--
-- Name: inquiry_item_inquiry_id_6d052293; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX inquiry_item_inquiry_id_6d052293 ON public.inquiry_item USING btree (inquiry_id);


--
-- Name: inquiry_owner_employee_id_884aac17; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX inquiry_owner_employee_id_884aac17 ON public.inquiry USING btree (owner_employee_id);


--
-- Name: inquiry_owner_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX inquiry_owner_status_idx ON public.inquiry USING btree (owner_employee_id, status, received_at DESC, id DESC) WHERE (archived_at IS NULL);


--
-- Name: inquiry_sla_link_inquiry_id_26597247; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX inquiry_sla_link_inquiry_id_26597247 ON public.inquiry_sla_link USING btree (inquiry_id);


--
-- Name: inquiry_status_list_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX inquiry_status_list_idx ON public.inquiry USING btree (status, received_at DESC, id DESC) WHERE (archived_at IS NULL);


--
-- Name: inquiry_task_link_business_task_id_8f84178c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX inquiry_task_link_business_task_id_8f84178c ON public.inquiry_task_link USING btree (business_task_id);


--
-- Name: inquiry_task_link_inquiry_id_826ba233; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX inquiry_task_link_inquiry_id_826ba233 ON public.inquiry_task_link USING btree (inquiry_id);


--
-- Name: inquiry_task_primary_uniq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX inquiry_task_primary_uniq ON public.inquiry_task_link USING btree (business_task_id) WHERE is_primary_source;


--
-- Name: inquiry_transaction_entity_id_d46c6465; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX inquiry_transaction_entity_id_d46c6465 ON public.inquiry USING btree (transaction_entity_id);


--
-- Name: org_unit_parent_active_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX org_unit_parent_active_idx ON public.organization_unit USING btree (parent_id, sort_order, id) WHERE (archived_at IS NULL);


--
-- Name: organization_unit_archived_by_employee_id_70addc6d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX organization_unit_archived_by_employee_id_70addc6d ON public.organization_unit USING btree (archived_by_employee_id);


--
-- Name: organization_unit_parent_id_ce577442; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX organization_unit_parent_id_ce577442 ON public.organization_unit USING btree (parent_id);


--
-- Name: organization_unit_unit_code_dcfeea9f_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX organization_unit_unit_code_dcfeea9f_like ON public.organization_unit USING btree (unit_code varchar_pattern_ops);


--
-- Name: quotation_accepted_version_id_0b94ac2f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_accepted_version_id_0b94ac2f ON public.quotation USING btree (accepted_version_id);


--
-- Name: quotation_archived_by_employee_id_8134295a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_archived_by_employee_id_8134295a ON public.quotation USING btree (archived_by_employee_id);


--
-- Name: quotation_customer_account_id_3fd95a8b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_customer_account_id_3fd95a8b ON public.quotation USING btree (customer_account_id);


--
-- Name: quotation_customer_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_customer_idx ON public.quotation USING btree (customer_account_id, created_at DESC, id DESC) WHERE (archived_at IS NULL);


--
-- Name: quotation_dispatch_record_dispatched_by_employee_id_b4321a6d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_dispatch_record_dispatched_by_employee_id_b4321a6d ON public.quotation_dispatch_record USING btree (dispatched_by_employee_id);


--
-- Name: quotation_dispatch_record_quotation_version_id_37c2c6d3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_dispatch_record_quotation_version_id_37c2c6d3 ON public.quotation_dispatch_record USING btree (quotation_version_id);


--
-- Name: quotation_document_business_file_id_dbf8483c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_document_business_file_id_dbf8483c ON public.quotation_document USING btree (business_file_id);


--
-- Name: quotation_document_generated_by_employee_id_9679e780; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_document_generated_by_employee_id_9679e780 ON public.quotation_document USING btree (generated_by_employee_id);


--
-- Name: quotation_document_quotation_version_id_e9604550; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_document_quotation_version_id_e9604550 ON public.quotation_document USING btree (quotation_version_id);


--
-- Name: quotation_entity_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_entity_idx ON public.quotation USING btree (transaction_entity_id, created_at DESC, id DESC) WHERE (archived_at IS NULL);


--
-- Name: quotation_file_link_business_file_id_fb42ab9d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_file_link_business_file_id_fb42ab9d ON public.quotation_file_link USING btree (business_file_id);


--
-- Name: quotation_file_link_quotation_version_id_1ff93d38; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_file_link_quotation_version_id_1ff93d38 ON public.quotation_file_link USING btree (quotation_version_id);


--
-- Name: quotation_inquiry_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_inquiry_idx ON public.quotation USING btree (source_inquiry_id, created_at DESC, id DESC) WHERE ((archived_at IS NULL) AND (source_inquiry_id IS NOT NULL));


--
-- Name: quotation_line_quotation_version_id_e3757ba8; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_line_quotation_version_id_e3757ba8 ON public.quotation_line USING btree (quotation_version_id);


--
-- Name: quotation_one_formal_doc_uniq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX quotation_one_formal_doc_uniq ON public.quotation_document USING btree (quotation_version_id) WHERE is_formal;


--
-- Name: quotation_owner_employee_id_340b6e14; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_owner_employee_id_340b6e14 ON public.quotation USING btree (owner_employee_id);


--
-- Name: quotation_owner_outcome_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_owner_outcome_idx ON public.quotation USING btree (owner_employee_id, outcome_status, updated_at DESC, id DESC) WHERE (archived_at IS NULL);


--
-- Name: quotation_quantity_tier_quotation_line_id_b22f47bc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_quantity_tier_quotation_line_id_b22f47bc ON public.quotation_quantity_tier USING btree (quotation_line_id);


--
-- Name: quotation_quotation_number_410c9d4a_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_quotation_number_410c9d4a_like ON public.quotation USING btree (quotation_number varchar_pattern_ops);


--
-- Name: quotation_source_inquiry_id_707a54cf; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_source_inquiry_id_707a54cf ON public.quotation USING btree (source_inquiry_id);


--
-- Name: quotation_task_primary_uniq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX quotation_task_primary_uniq ON public.quotation_version_task_link USING btree (business_task_id) WHERE is_primary_source;


--
-- Name: quotation_template_archived_by_employee_id_04b5bed5; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_template_archived_by_employee_id_04b5bed5 ON public.quotation_template USING btree (archived_by_employee_id);


--
-- Name: quotation_template_template_code_ee4f9413_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_template_template_code_ee4f9413_like ON public.quotation_template USING btree (template_code varchar_pattern_ops);


--
-- Name: quotation_transaction_entity_id_4918e8f1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_transaction_entity_id_4918e8f1 ON public.quotation USING btree (transaction_entity_id);


--
-- Name: quotation_version_approval_link_quotation_version_id_fbcf23e0; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_version_approval_link_quotation_version_id_fbcf23e0 ON public.quotation_version_approval_link USING btree (quotation_version_id);


--
-- Name: quotation_version_locked_by_employee_id_02d7baa2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_version_locked_by_employee_id_02d7baa2 ON public.quotation_version USING btree (locked_by_employee_id);


--
-- Name: quotation_version_quotation_id_66606047; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_version_quotation_id_66606047 ON public.quotation_version USING btree (quotation_id);


--
-- Name: quotation_version_quotation_template_id_da27a219; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_version_quotation_template_id_da27a219 ON public.quotation_version USING btree (quotation_template_id);


--
-- Name: quotation_version_sla_link_quotation_version_id_cc010fde; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_version_sla_link_quotation_version_id_cc010fde ON public.quotation_version_sla_link USING btree (quotation_version_id);


--
-- Name: quotation_version_task_link_business_task_id_bd25ba77; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_version_task_link_business_task_id_bd25ba77 ON public.quotation_version_task_link USING btree (business_task_id);


--
-- Name: quotation_version_task_link_quotation_version_id_0b5f7e1c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quotation_version_task_link_quotation_version_id_0b5f7e1c ON public.quotation_version_task_link USING btree (quotation_version_id);


--
-- Name: quote_dispatch_followup_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quote_dispatch_followup_idx ON public.quotation_dispatch_record USING btree (follow_up_due_at, id) WHERE ((follow_up_due_at IS NOT NULL) AND ((follow_up_status)::text = 'PENDING'::text));


--
-- Name: quote_dispatch_history_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quote_dispatch_history_idx ON public.quotation_dispatch_record USING btree (quotation_version_id, dispatched_at DESC, id DESC);


--
-- Name: quote_version_expiry_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quote_version_expiry_idx ON public.quotation_version USING btree (valid_until, id) WHERE (((status)::text = ANY ((ARRAY['ISSUED'::character varying, 'SENT'::character varying])::text[])) AND (valid_until IS NOT NULL));


--
-- Name: quote_version_issued_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX quote_version_issued_idx ON public.quotation_version USING btree (status, issued_at DESC, id DESC) WHERE ((status)::text = ANY ((ARRAY['ISSUED'::character varying, 'SENT'::character varying])::text[]));


--
-- Name: ref_dict_active_list_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ref_dict_active_list_idx ON public.reference_dictionary USING btree (category_code, status, sort_order, id) WHERE (archived_at IS NULL);


--
-- Name: reference_dictionary_archived_by_employee_id_45e1a5d4; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX reference_dictionary_archived_by_employee_id_45e1a5d4 ON public.reference_dictionary USING btree (archived_by_employee_id);


--
-- Name: role_profile_archived_by_employee_id_b7931a63; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX role_profile_archived_by_employee_id_b7931a63 ON public.role_profile USING btree (archived_by_employee_id);


--
-- Name: role_profile_role_code_ffef6c49_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX role_profile_role_code_ffef6c49_like ON public.role_profile USING btree (role_code varchar_pattern_ops);


--
-- Name: sample_approval_link_sample_request_id_f0d11809; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_approval_link_sample_request_id_f0d11809 ON public.sample_approval_link USING btree (sample_request_id);


--
-- Name: sample_customer_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_customer_idx ON public.sample_request USING btree (customer_account_id, requested_at DESC, id DESC) WHERE (archived_at IS NULL);


--
-- Name: sample_fee_current_record_uniq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX sample_fee_current_record_uniq ON public.sample_fee_record USING btree (sample_request_id) WHERE (superseded_at IS NULL);


--
-- Name: sample_fee_record_decided_by_employee_id_bf3bb4a8; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_fee_record_decided_by_employee_id_bf3bb4a8 ON public.sample_fee_record USING btree (decided_by_employee_id);


--
-- Name: sample_fee_record_sample_request_id_9662b953; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_fee_record_sample_request_id_9662b953 ON public.sample_fee_record USING btree (sample_request_id);


--
-- Name: sample_feedback_customer_contact_id_87d5966b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_feedback_customer_contact_id_87d5966b ON public.sample_feedback USING btree (customer_contact_id);


--
-- Name: sample_feedback_history_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_feedback_history_idx ON public.sample_feedback USING btree (sample_request_id, occurred_at DESC, id DESC);


--
-- Name: sample_feedback_recorded_by_employee_id_b85309b4; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_feedback_recorded_by_employee_id_b85309b4 ON public.sample_feedback USING btree (recorded_by_employee_id);


--
-- Name: sample_feedback_sample_request_id_c8308873; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_feedback_sample_request_id_c8308873 ON public.sample_feedback USING btree (sample_request_id);


--
-- Name: sample_file_link_business_file_id_8b7fe3f8; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_file_link_business_file_id_8b7fe3f8 ON public.sample_file_link USING btree (business_file_id);


--
-- Name: sample_file_link_sample_request_id_108b58ee; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_file_link_sample_request_id_108b58ee ON public.sample_file_link USING btree (sample_request_id);


--
-- Name: sample_inquiry_source_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_inquiry_source_idx ON public.sample_request USING btree (source_inquiry_id, requested_at DESC, id DESC) WHERE (source_inquiry_id IS NOT NULL);


--
-- Name: sample_item_sample_request_id_e21ad888; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_item_sample_request_id_e21ad888 ON public.sample_item USING btree (sample_request_id);


--
-- Name: sample_owner_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_owner_status_idx ON public.sample_request USING btree (owner_employee_id, status, updated_at DESC, id DESC) WHERE (archived_at IS NULL);


--
-- Name: sample_processing_queue_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_processing_queue_idx ON public.sample_request USING btree (status, requested_at, id) WHERE ((archived_at IS NULL) AND ((status)::text = ANY ((ARRAY['PENDING'::character varying, 'PREPARING'::character varying, 'SHIPPED'::character varying, 'FEEDBACK_PENDING'::character varying])::text[])));


--
-- Name: sample_quote_source_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_quote_source_idx ON public.sample_request USING btree (source_quotation_version_id, requested_at DESC, id DESC) WHERE (source_quotation_version_id IS NOT NULL);


--
-- Name: sample_request_archived_by_employee_id_e485ab75; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_request_archived_by_employee_id_e485ab75 ON public.sample_request USING btree (archived_by_employee_id);


--
-- Name: sample_request_customer_account_id_7f3f13f0; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_request_customer_account_id_7f3f13f0 ON public.sample_request USING btree (customer_account_id);


--
-- Name: sample_request_customer_contact_id_8b8b27a5; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_request_customer_contact_id_8b8b27a5 ON public.sample_request USING btree (customer_contact_id);


--
-- Name: sample_request_owner_employee_id_7e050fae; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_request_owner_employee_id_7e050fae ON public.sample_request USING btree (owner_employee_id);


--
-- Name: sample_request_request_number_6b599b79_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_request_request_number_6b599b79_like ON public.sample_request USING btree (request_number varchar_pattern_ops);


--
-- Name: sample_request_source_inquiry_id_8e52ce29; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_request_source_inquiry_id_8e52ce29 ON public.sample_request USING btree (source_inquiry_id);


--
-- Name: sample_request_source_quotation_version_id_0d70c589; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_request_source_quotation_version_id_0d70c589 ON public.sample_request USING btree (source_quotation_version_id);


--
-- Name: sample_request_transaction_entity_id_f6126e8c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_request_transaction_entity_id_f6126e8c ON public.sample_request USING btree (transaction_entity_id);


--
-- Name: sample_shipment_fee_warning_acknowledged_b_1e536815; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_shipment_fee_warning_acknowledged_b_1e536815 ON public.sample_shipment USING btree (fee_warning_acknowledged_by_employee_id);


--
-- Name: sample_shipment_history_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_shipment_history_idx ON public.sample_shipment USING btree (sample_request_id, shipped_at DESC, id DESC);


--
-- Name: sample_shipment_item_sample_item_id_ce7acb07; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_shipment_item_sample_item_id_ce7acb07 ON public.sample_shipment_item USING btree (sample_item_id);


--
-- Name: sample_shipment_item_sample_shipment_id_dbd71529; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_shipment_item_sample_shipment_id_dbd71529 ON public.sample_shipment_item USING btree (sample_shipment_id);


--
-- Name: sample_shipment_sample_request_id_45fbecbe; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_shipment_sample_request_id_45fbecbe ON public.sample_shipment USING btree (sample_request_id);


--
-- Name: sample_shipment_shipped_by_employee_id_19bdee0f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_shipment_shipped_by_employee_id_19bdee0f ON public.sample_shipment USING btree (shipped_by_employee_id);


--
-- Name: sample_sla_link_sample_request_id_05764df3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_sla_link_sample_request_id_05764df3 ON public.sample_sla_link USING btree (sample_request_id);


--
-- Name: sample_task_link_business_task_id_e25c4d49; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_task_link_business_task_id_e25c4d49 ON public.sample_task_link USING btree (business_task_id);


--
-- Name: sample_task_link_sample_request_id_508894f2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_task_link_sample_request_id_508894f2 ON public.sample_task_link USING btree (sample_request_id);


--
-- Name: sample_task_primary_uniq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX sample_task_primary_uniq ON public.sample_task_link USING btree (business_task_id) WHERE is_primary_source;


--
-- Name: sample_tracking_lookup_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sample_tracking_lookup_idx ON public.sample_shipment USING btree (carrier_code, tracking_number) WHERE (NOT ((tracking_number)::text = ''::text));


--
-- Name: saved_view_active_name_uniq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX saved_view_active_name_uniq ON public.saved_view USING btree (employee_id, module_code, view_name) WHERE (archived_at IS NULL);


--
-- Name: saved_view_archived_by_employee_id_86f69b95; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX saved_view_archived_by_employee_id_86f69b95 ON public.saved_view USING btree (archived_by_employee_id);


--
-- Name: saved_view_employee_id_ed85d6be; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX saved_view_employee_id_ed85d6be ON public.saved_view USING btree (employee_id);


--
-- Name: saved_view_employee_module_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX saved_view_employee_module_idx ON public.saved_view USING btree (employee_id, module_code, sort_order, id) WHERE (archived_at IS NULL);


--
-- Name: saved_view_one_default_uniq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX saved_view_one_default_uniq ON public.saved_view USING btree (employee_id, module_code) WHERE ((archived_at IS NULL) AND is_default);


--
-- Name: sla_policy_archived_by_employee_id_85953882; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sla_policy_archived_by_employee_id_85953882 ON public.sla_policy USING btree (archived_by_employee_id);


--
-- Name: sla_policy_policy_code_5ea9f780_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sla_policy_policy_code_5ea9f780_like ON public.sla_policy USING btree (policy_code varchar_pattern_ops);


--
-- Name: sla_running_deadline_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sla_running_deadline_idx ON public.sla_tracking USING btree (status, next_deadline_at, id) WHERE ((status)::text = 'RUNNING'::text);


--
-- Name: sla_tracking_sla_policy_id_51aa403c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sla_tracking_sla_policy_id_51aa403c ON public.sla_tracking USING btree (sla_policy_id);


--
-- Name: task_assignee_open_due_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX task_assignee_open_due_idx ON public.business_task USING btree (assignee_employee_id, due_at, id) WHERE ((archived_at IS NULL) AND ((status)::text = ANY ((ARRAY['PENDING'::character varying, 'IN_PROGRESS'::character varying])::text[])));


--
-- Name: task_open_due_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX task_open_due_idx ON public.business_task USING btree (status, due_at, id) WHERE ((archived_at IS NULL) AND ((status)::text = ANY ((ARRAY['PENDING'::character varying, 'IN_PROGRESS'::character varying])::text[])));


--
-- Name: timeline_customer_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX timeline_customer_idx ON public.customer_timeline_event USING btree (customer_account_id, occurred_at DESC, id DESC);


--
-- Name: timeline_source_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX timeline_source_idx ON public.customer_timeline_event USING btree (source_type, source_id);


--
-- Name: audit_log audit_log_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER audit_log_append_only BEFORE DELETE OR UPDATE ON public.audit_log FOR EACH ROW EXECUTE FUNCTION public.haiqu_block_row_change();


--
-- Name: communication_contact_participant communication_contact_consistency_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER communication_contact_consistency_guard BEFORE INSERT OR UPDATE ON public.communication_contact_participant FOR EACH ROW EXECUTE FUNCTION public.haiqu_check_communication_link();


--
-- Name: communication_inquiry_link communication_inquiry_consistency_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER communication_inquiry_consistency_guard BEFORE INSERT OR UPDATE ON public.communication_inquiry_link FOR EACH ROW EXECUTE FUNCTION public.haiqu_check_communication_link();


--
-- Name: communication_quotation_version_link communication_quote_consistency_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER communication_quote_consistency_guard BEFORE INSERT OR UPDATE ON public.communication_quotation_version_link FOR EACH ROW EXECUTE FUNCTION public.haiqu_check_communication_link();


--
-- Name: communication_sample_request_link communication_sample_consistency_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER communication_sample_consistency_guard BEFORE INSERT OR UPDATE ON public.communication_sample_request_link FOR EACH ROW EXECUTE FUNCTION public.haiqu_check_communication_link();


--
-- Name: customer_contact customer_contact_consistency_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER customer_contact_consistency_guard BEFORE INSERT OR UPDATE OF customer_account_id, transaction_entity_id, source_contact_id ON public.customer_contact FOR EACH ROW EXECUTE FUNCTION public.haiqu_check_customer_contact();


--
-- Name: customer_merge_operation customer_merge_completion_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER customer_merge_completion_guard BEFORE INSERT OR UPDATE OF status, executed_at ON public.customer_merge_operation FOR EACH ROW EXECUTE FUNCTION public.haiqu_check_customer_merge_completion();


--
-- Name: customer_merge_member customer_merge_member_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER customer_merge_member_guard BEFORE INSERT OR DELETE OR UPDATE ON public.customer_merge_member FOR EACH ROW EXECUTE FUNCTION public.haiqu_guard_customer_merge_member();


--
-- Name: inquiry inquiry_consistency_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER inquiry_consistency_guard BEFORE INSERT OR UPDATE OF customer_account_id, transaction_entity_id, customer_contact_id, status ON public.inquiry FOR EACH ROW EXECUTE FUNCTION public.haiqu_check_inquiry();


--
-- Name: inquiry_item inquiry_item_cardinality_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER inquiry_item_cardinality_guard AFTER DELETE ON public.inquiry_item DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.haiqu_check_inquiry_has_item();


--
-- Name: organization_unit organization_parent_cycle_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER organization_parent_cycle_guard BEFORE INSERT OR UPDATE OF parent_id ON public.organization_unit FOR EACH ROW EXECUTE FUNCTION public.haiqu_check_organization_parent();


--
-- Name: quotation quotation_consistency_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER quotation_consistency_guard BEFORE INSERT OR UPDATE OF customer_account_id, transaction_entity_id, source_inquiry_id, accepted_version_id, outcome_status ON public.quotation FOR EACH ROW EXECUTE FUNCTION public.haiqu_check_quotation();


--
-- Name: quotation_line quotation_line_lock_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER quotation_line_lock_guard BEFORE INSERT OR DELETE OR UPDATE ON public.quotation_line FOR EACH ROW EXECUTE FUNCTION public.haiqu_guard_quotation_line();


--
-- Name: quotation_quantity_tier quotation_tier_lock_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER quotation_tier_lock_guard BEFORE INSERT OR DELETE OR UPDATE ON public.quotation_quantity_tier FOR EACH ROW EXECUTE FUNCTION public.haiqu_guard_quotation_tier();


--
-- Name: quotation_version quotation_version_snapshot_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER quotation_version_snapshot_guard BEFORE INSERT OR UPDATE ON public.quotation_version FOR EACH ROW EXECUTE FUNCTION public.haiqu_guard_quotation_version();


--
-- Name: sample_item sample_item_cardinality_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER sample_item_cardinality_guard AFTER DELETE ON public.sample_item DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.haiqu_check_sample_has_item();


--
-- Name: sample_request sample_request_consistency_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER sample_request_consistency_guard BEFORE INSERT OR UPDATE OF customer_account_id, transaction_entity_id, customer_contact_id, source_inquiry_id, source_quotation_version_id, status ON public.sample_request FOR EACH ROW EXECUTE FUNCTION public.haiqu_check_sample_request();


--
-- Name: sample_shipment sample_shipment_consistency_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER sample_shipment_consistency_guard BEFORE INSERT OR UPDATE ON public.sample_shipment FOR EACH ROW EXECUTE FUNCTION public.haiqu_check_sample_shipment();


--
-- Name: sample_shipment_item sample_shipment_item_consistency_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER sample_shipment_item_consistency_guard BEFORE INSERT OR DELETE OR UPDATE ON public.sample_shipment_item FOR EACH ROW EXECUTE FUNCTION public.haiqu_check_sample_shipment_item();


--
-- Name: approval_request approval_request_current_approver_emp_0adc7768_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_request
    ADD CONSTRAINT approval_request_current_approver_emp_0adc7768_fk_employee_ FOREIGN KEY (current_approver_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: approval_request approval_request_requested_by_employe_edf269a6_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_request
    ADD CONSTRAINT approval_request_requested_by_employe_edf269a6_fk_employee_ FOREIGN KEY (requested_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: audit_log audit_log_actor_employee_id_cfc825de_fk_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_actor_employee_id_cfc825de_fk_employee_id FOREIGN KEY (actor_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_group_permissions auth_group_permissio_permission_id_84c5c92e_fk_auth_perm; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissio_permission_id_84c5c92e_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES public.auth_permission(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_group_permissions auth_group_permissions_group_id_b120cbf9_fk_auth_group_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_group_id_b120cbf9_fk_auth_group_id FOREIGN KEY (group_id) REFERENCES public.auth_group(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_permission auth_permission_content_type_id_2f476e4b_fk_django_co; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_content_type_id_2f476e4b_fk_django_co FOREIGN KEY (content_type_id) REFERENCES public.django_content_type(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_user_groups auth_user_groups_group_id_97559544_fk_auth_group_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_groups
    ADD CONSTRAINT auth_user_groups_group_id_97559544_fk_auth_group_id FOREIGN KEY (group_id) REFERENCES public.auth_group(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_user_groups auth_user_groups_user_id_6a12ed8b_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_groups
    ADD CONSTRAINT auth_user_groups_user_id_6a12ed8b_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_user_user_permissions auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_user_permissions
    ADD CONSTRAINT auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES public.auth_permission(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_user_user_permissions auth_user_user_permissions_user_id_a95ead1b_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_user_permissions
    ADD CONSTRAINT auth_user_user_permissions_user_id_a95ead1b_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: business_file business_file_archived_by_employee_id_bf8b1e3a_fk_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.business_file
    ADD CONSTRAINT business_file_archived_by_employee_id_bf8b1e3a_fk_employee_id FOREIGN KEY (archived_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: business_file business_file_uploaded_by_employee_id_edfa1024_fk_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.business_file
    ADD CONSTRAINT business_file_uploaded_by_employee_id_edfa1024_fk_employee_id FOREIGN KEY (uploaded_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: business_task business_task_archived_by_employee_id_4dcc5ec7_fk_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.business_task
    ADD CONSTRAINT business_task_archived_by_employee_id_4dcc5ec7_fk_employee_id FOREIGN KEY (archived_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: business_task business_task_assignee_employee_id_7278676f_fk_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.business_task
    ADD CONSTRAINT business_task_assignee_employee_id_7278676f_fk_employee_id FOREIGN KEY (assignee_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: business_task business_task_created_by_employee_id_edca13ae_fk_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.business_task
    ADD CONSTRAINT business_task_created_by_employee_id_edca13ae_fk_employee_id FOREIGN KEY (created_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: communication_contact_participant communication_contac_communication_id_c6edb269_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_contact_participant
    ADD CONSTRAINT communication_contac_communication_id_c6edb269_fk_customer_ FOREIGN KEY (communication_id) REFERENCES public.customer_communication(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: communication_contact_participant communication_contac_customer_contact_id_c6ee9af5_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_contact_participant
    ADD CONSTRAINT communication_contac_customer_contact_id_c6ee9af5_fk_customer_ FOREIGN KEY (customer_contact_id) REFERENCES public.customer_contact(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: communication_employee_participant communication_employ_communication_id_587e4354_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_employee_participant
    ADD CONSTRAINT communication_employ_communication_id_587e4354_fk_customer_ FOREIGN KEY (communication_id) REFERENCES public.customer_communication(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: communication_employee_participant communication_employ_employee_id_1079d64e_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_employee_participant
    ADD CONSTRAINT communication_employ_employee_id_1079d64e_fk_employee_ FOREIGN KEY (employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: communication_file_link communication_file_l_business_file_id_bd9f280c_fk_business_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_file_link
    ADD CONSTRAINT communication_file_l_business_file_id_bd9f280c_fk_business_ FOREIGN KEY (business_file_id) REFERENCES public.business_file(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: communication_file_link communication_file_l_communication_id_67ea505c_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_file_link
    ADD CONSTRAINT communication_file_l_communication_id_67ea505c_fk_customer_ FOREIGN KEY (communication_id) REFERENCES public.customer_communication(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: communication_inquiry_link communication_inquir_communication_id_ef83aa86_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_inquiry_link
    ADD CONSTRAINT communication_inquir_communication_id_ef83aa86_fk_customer_ FOREIGN KEY (communication_id) REFERENCES public.customer_communication(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: communication_inquiry_link communication_inquiry_link_inquiry_id_0614c444_fk_inquiry_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_inquiry_link
    ADD CONSTRAINT communication_inquiry_link_inquiry_id_0614c444_fk_inquiry_id FOREIGN KEY (inquiry_id) REFERENCES public.inquiry(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: communication_quotation_version_link communication_quotat_communication_id_bb222218_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_quotation_version_link
    ADD CONSTRAINT communication_quotat_communication_id_bb222218_fk_customer_ FOREIGN KEY (communication_id) REFERENCES public.customer_communication(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: communication_quotation_version_link communication_quotat_quotation_version_id_508c9377_fk_quotation; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_quotation_version_link
    ADD CONSTRAINT communication_quotat_quotation_version_id_508c9377_fk_quotation FOREIGN KEY (quotation_version_id) REFERENCES public.quotation_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: communication_sample_request_link communication_sample_communication_id_85f01af4_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_sample_request_link
    ADD CONSTRAINT communication_sample_communication_id_85f01af4_fk_customer_ FOREIGN KEY (communication_id) REFERENCES public.customer_communication(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: communication_sample_request_link communication_sample_sample_request_id_0b0d2f5d_fk_sample_re; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_sample_request_link
    ADD CONSTRAINT communication_sample_sample_request_id_0b0d2f5d_fk_sample_re FOREIGN KEY (sample_request_id) REFERENCES public.sample_request(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: communication_task_link communication_task_l_business_task_id_22a779fe_fk_business_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_task_link
    ADD CONSTRAINT communication_task_l_business_task_id_22a779fe_fk_business_ FOREIGN KEY (business_task_id) REFERENCES public.business_task(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: communication_task_link communication_task_l_communication_id_3f635540_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.communication_task_link
    ADD CONSTRAINT communication_task_l_communication_id_3f635540_fk_customer_ FOREIGN KEY (communication_id) REFERENCES public.customer_communication(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_account customer_account_archived_by_employee_e9c5dbdf_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_account
    ADD CONSTRAINT customer_account_archived_by_employee_e9c5dbdf_fk_employee_ FOREIGN KEY (archived_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_assignment customer_assignment_assigned_by_employee_ecc3f689_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_assignment
    ADD CONSTRAINT customer_assignment_assigned_by_employee_ecc3f689_fk_employee_ FOREIGN KEY (assigned_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_assignment customer_assignment_customer_account_id_83f569b2_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_assignment
    ADD CONSTRAINT customer_assignment_customer_account_id_83f569b2_fk_customer_ FOREIGN KEY (customer_account_id) REFERENCES public.customer_account(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_assignment customer_assignment_employee_id_c370c440_fk_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_assignment
    ADD CONSTRAINT customer_assignment_employee_id_c370c440_fk_employee_id FOREIGN KEY (employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_attention_review customer_attention_r_attention_level_item_48ccf133_fk_reference; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_attention_review
    ADD CONSTRAINT customer_attention_r_attention_level_item_48ccf133_fk_reference FOREIGN KEY (attention_level_item_id) REFERENCES public.reference_dictionary(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_attention_review customer_attention_r_customer_account_id_2d6b266b_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_attention_review
    ADD CONSTRAINT customer_attention_r_customer_account_id_2d6b266b_fk_customer_ FOREIGN KEY (customer_account_id) REFERENCES public.customer_account(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_attention_review customer_attention_r_reviewed_by_employee_a3822f3e_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_attention_review
    ADD CONSTRAINT customer_attention_r_reviewed_by_employee_a3822f3e_fk_employee_ FOREIGN KEY (reviewed_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_communication customer_communicati_archived_by_employee_4fda484c_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_communication
    ADD CONSTRAINT customer_communicati_archived_by_employee_4fda484c_fk_employee_ FOREIGN KEY (archived_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_communication customer_communicati_created_by_employee__6699ec01_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_communication
    ADD CONSTRAINT customer_communicati_created_by_employee__6699ec01_fk_employee_ FOREIGN KEY (created_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_communication customer_communicati_customer_account_id_ad398c9c_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_communication
    ADD CONSTRAINT customer_communicati_customer_account_id_ad398c9c_fk_customer_ FOREIGN KEY (customer_account_id) REFERENCES public.customer_account(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_contact customer_contact_archived_by_employee_732bfa6e_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_contact
    ADD CONSTRAINT customer_contact_archived_by_employee_732bfa6e_fk_employee_ FOREIGN KEY (archived_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_contact customer_contact_customer_account_id_aba0cdd7_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_contact
    ADD CONSTRAINT customer_contact_customer_account_id_aba0cdd7_fk_customer_ FOREIGN KEY (customer_account_id) REFERENCES public.customer_account(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_contact_method customer_contact_met_archived_by_employee_abe7cbaa_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_contact_method
    ADD CONSTRAINT customer_contact_met_archived_by_employee_abe7cbaa_fk_employee_ FOREIGN KEY (archived_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_contact_method customer_contact_met_customer_contact_id_1e76c682_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_contact_method
    ADD CONSTRAINT customer_contact_met_customer_contact_id_1e76c682_fk_customer_ FOREIGN KEY (customer_contact_id) REFERENCES public.customer_contact(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_contact_role customer_contact_rol_customer_contact_id_0e06cf8b_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_contact_role
    ADD CONSTRAINT customer_contact_rol_customer_contact_id_0e06cf8b_fk_customer_ FOREIGN KEY (customer_contact_id) REFERENCES public.customer_contact(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_contact customer_contact_source_contact_id_80f80a04_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_contact
    ADD CONSTRAINT customer_contact_source_contact_id_80f80a04_fk_customer_ FOREIGN KEY (source_contact_id) REFERENCES public.customer_contact(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_contact customer_contact_transaction_entity_i_f02a47d9_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_contact
    ADD CONSTRAINT customer_contact_transaction_entity_i_f02a47d9_fk_customer_ FOREIGN KEY (transaction_entity_id) REFERENCES public.customer_transaction_entity(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_data_access_grant customer_data_access_customer_account_id_3d17feb1_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_data_access_grant
    ADD CONSTRAINT customer_data_access_customer_account_id_3d17feb1_fk_customer_ FOREIGN KEY (customer_account_id) REFERENCES public.customer_account(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_data_access_grant customer_data_access_grant_employee_id_ce3fa450_fk_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_data_access_grant
    ADD CONSTRAINT customer_data_access_grant_employee_id_ce3fa450_fk_employee_id FOREIGN KEY (employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_data_access_grant customer_data_access_granted_by_employee__d1df79f9_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_data_access_grant
    ADD CONSTRAINT customer_data_access_granted_by_employee__d1df79f9_fk_employee_ FOREIGN KEY (granted_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_data_access_grant customer_data_access_permission_id_7e511200_fk_auth_perm; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_data_access_grant
    ADD CONSTRAINT customer_data_access_permission_id_7e511200_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES public.auth_permission(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_data_access_grant customer_data_access_revoked_by_employee__5e1b2a69_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_data_access_grant
    ADD CONSTRAINT customer_data_access_revoked_by_employee__5e1b2a69_fk_employee_ FOREIGN KEY (revoked_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_duplicate_candidate customer_duplicate_c_customer_account_id_f2bbab56_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_duplicate_candidate
    ADD CONSTRAINT customer_duplicate_c_customer_account_id_f2bbab56_fk_customer_ FOREIGN KEY (customer_account_id) REFERENCES public.customer_account(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_duplicate_candidate customer_duplicate_c_duplicate_case_id_e28005df_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_duplicate_candidate
    ADD CONSTRAINT customer_duplicate_c_duplicate_case_id_e28005df_fk_customer_ FOREIGN KEY (duplicate_case_id) REFERENCES public.customer_duplicate_case(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_duplicate_case customer_duplicate_c_reviewer_employee_id_dc16922c_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_duplicate_case
    ADD CONSTRAINT customer_duplicate_c_reviewer_employee_id_dc16922c_fk_employee_ FOREIGN KEY (reviewer_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_entity_address customer_entity_addr_archived_by_employee_df272d5d_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_entity_address
    ADD CONSTRAINT customer_entity_addr_archived_by_employee_df272d5d_fk_employee_ FOREIGN KEY (archived_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_entity_address_usage customer_entity_addr_entity_address_id_06ea6f4a_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_entity_address_usage
    ADD CONSTRAINT customer_entity_addr_entity_address_id_06ea6f4a_fk_customer_ FOREIGN KEY (entity_address_id) REFERENCES public.customer_entity_address(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_entity_address customer_entity_addr_transaction_entity_i_d1630a0d_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_entity_address
    ADD CONSTRAINT customer_entity_addr_transaction_entity_i_d1630a0d_fk_customer_ FOREIGN KEY (transaction_entity_id) REFERENCES public.customer_transaction_entity(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_file_link customer_file_link_business_file_id_846696e0_fk_business_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_file_link
    ADD CONSTRAINT customer_file_link_business_file_id_846696e0_fk_business_ FOREIGN KEY (business_file_id) REFERENCES public.business_file(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_file_link customer_file_link_customer_account_id_af14e4eb_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_file_link
    ADD CONSTRAINT customer_file_link_customer_account_id_af14e4eb_fk_customer_ FOREIGN KEY (customer_account_id) REFERENCES public.customer_account(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_historical_transaction_confirmation customer_historical__confirmed_by_employe_609e0281_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_historical_transaction_confirmation
    ADD CONSTRAINT customer_historical__confirmed_by_employe_609e0281_fk_employee_ FOREIGN KEY (confirmed_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_historical_transaction_confirmation customer_historical__customer_account_id_a14c19e5_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_historical_transaction_confirmation
    ADD CONSTRAINT customer_historical__customer_account_id_a14c19e5_fk_customer_ FOREIGN KEY (customer_account_id) REFERENCES public.customer_account(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_merge_change customer_merge_chang_merge_operation_id_d99df7ea_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_merge_change
    ADD CONSTRAINT customer_merge_chang_merge_operation_id_d99df7ea_fk_customer_ FOREIGN KEY (merge_operation_id) REFERENCES public.customer_merge_operation(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_merge_member customer_merge_membe_customer_account_id_cfb19112_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_merge_member
    ADD CONSTRAINT customer_merge_membe_customer_account_id_cfb19112_fk_customer_ FOREIGN KEY (customer_account_id) REFERENCES public.customer_account(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_merge_member customer_merge_membe_merge_operation_id_7450a503_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_merge_member
    ADD CONSTRAINT customer_merge_membe_merge_operation_id_7450a503_fk_customer_ FOREIGN KEY (merge_operation_id) REFERENCES public.customer_merge_operation(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_merge_operation customer_merge_opera_duplicate_case_id_ccf89ae5_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_merge_operation
    ADD CONSTRAINT customer_merge_opera_duplicate_case_id_ccf89ae5_fk_customer_ FOREIGN KEY (duplicate_case_id) REFERENCES public.customer_duplicate_case(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_merge_operation customer_merge_opera_executed_by_employee_606dd1fa_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_merge_operation
    ADD CONSTRAINT customer_merge_opera_executed_by_employee_606dd1fa_fk_employee_ FOREIGN KEY (executed_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_task_link customer_task_link_business_task_id_f4bd0194_fk_business_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_task_link
    ADD CONSTRAINT customer_task_link_business_task_id_f4bd0194_fk_business_ FOREIGN KEY (business_task_id) REFERENCES public.business_task(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_task_link customer_task_link_customer_account_id_29c2112e_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_task_link
    ADD CONSTRAINT customer_task_link_customer_account_id_29c2112e_fk_customer_ FOREIGN KEY (customer_account_id) REFERENCES public.customer_account(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_timeline_event customer_timeline_ev_customer_account_id_cf506f25_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_timeline_event
    ADD CONSTRAINT customer_timeline_ev_customer_account_id_cf506f25_fk_customer_ FOREIGN KEY (customer_account_id) REFERENCES public.customer_account(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_transaction_entity customer_transaction_archived_by_employee_54120e98_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_transaction_entity
    ADD CONSTRAINT customer_transaction_archived_by_employee_54120e98_fk_employee_ FOREIGN KEY (archived_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_transaction_entity customer_transaction_customer_account_id_a617d899_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_transaction_entity
    ADD CONSTRAINT customer_transaction_customer_account_id_a617d899_fk_customer_ FOREIGN KEY (customer_account_id) REFERENCES public.customer_account(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_transaction_entity_role customer_transaction_transaction_entity_i_5536377e_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_transaction_entity_role
    ADD CONSTRAINT customer_transaction_transaction_entity_i_5536377e_fk_customer_ FOREIGN KEY (transaction_entity_id) REFERENCES public.customer_transaction_entity(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_transfer_request customer_transfer_re_customer_account_id_18719b53_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_transfer_request
    ADD CONSTRAINT customer_transfer_re_customer_account_id_18719b53_fk_customer_ FOREIGN KEY (customer_account_id) REFERENCES public.customer_account(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_transfer_request customer_transfer_re_decided_by_employee__5c5ebaee_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_transfer_request
    ADD CONSTRAINT customer_transfer_re_decided_by_employee__5c5ebaee_fk_employee_ FOREIGN KEY (decided_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_transfer_request customer_transfer_re_from_employee_id_53f242cb_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_transfer_request
    ADD CONSTRAINT customer_transfer_re_from_employee_id_53f242cb_fk_employee_ FOREIGN KEY (from_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_transfer_request customer_transfer_re_requested_by_employe_62060bc0_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_transfer_request
    ADD CONSTRAINT customer_transfer_re_requested_by_employe_62060bc0_fk_employee_ FOREIGN KEY (requested_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: customer_transfer_request customer_transfer_re_to_employee_id_b45dd562_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customer_transfer_request
    ADD CONSTRAINT customer_transfer_re_to_employee_id_b45dd562_fk_employee_ FOREIGN KEY (to_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: django_admin_log django_admin_log_content_type_id_c4bce8eb_fk_django_co; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_admin_log
    ADD CONSTRAINT django_admin_log_content_type_id_c4bce8eb_fk_django_co FOREIGN KEY (content_type_id) REFERENCES public.django_content_type(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: django_admin_log django_admin_log_user_id_c564eba6_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_admin_log
    ADD CONSTRAINT django_admin_log_user_id_c564eba6_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: employee employee_archived_by_employee_id_c2520dab_fk_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee
    ADD CONSTRAINT employee_archived_by_employee_id_c2520dab_fk_employee_id FOREIGN KEY (archived_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: employee_organization_assignment employee_organizatio_assigned_by_employee_ab17938c_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee_organization_assignment
    ADD CONSTRAINT employee_organizatio_assigned_by_employee_ab17938c_fk_employee_ FOREIGN KEY (assigned_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: employee_organization_assignment employee_organizatio_employee_id_5e606490_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee_organization_assignment
    ADD CONSTRAINT employee_organizatio_employee_id_5e606490_fk_employee_ FOREIGN KEY (employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: employee_organization_assignment employee_organizatio_organization_unit_id_9012096f_fk_organizat; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee_organization_assignment
    ADD CONSTRAINT employee_organizatio_organization_unit_id_9012096f_fk_organizat FOREIGN KEY (organization_unit_id) REFERENCES public.organization_unit(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: employee_role_assignment employee_role_assign_assigned_by_employee_801ccc70_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee_role_assignment
    ADD CONSTRAINT employee_role_assign_assigned_by_employee_801ccc70_fk_employee_ FOREIGN KEY (assigned_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: employee_role_assignment employee_role_assign_role_profile_id_d7376146_fk_role_prof; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee_role_assignment
    ADD CONSTRAINT employee_role_assign_role_profile_id_d7376146_fk_role_prof FOREIGN KEY (role_profile_id) REFERENCES public.role_profile(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: employee_role_assignment employee_role_assignment_employee_id_eb614ca7_fk_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee_role_assignment
    ADD CONSTRAINT employee_role_assignment_employee_id_eb614ca7_fk_employee_id FOREIGN KEY (employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: employee employee_user_id_cc4f5a1c_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee
    ADD CONSTRAINT employee_user_id_cc4f5a1c_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: import_batch import_batch_created_by_employee_id_441d15e7_fk_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_batch
    ADD CONSTRAINT import_batch_created_by_employee_id_441d15e7_fk_employee_id FOREIGN KEY (created_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: import_batch import_batch_source_file_id_a90307e5_fk_business_file_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_batch
    ADD CONSTRAINT import_batch_source_file_id_a90307e5_fk_business_file_id FOREIGN KEY (source_file_id) REFERENCES public.business_file(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: import_record import_record_import_batch_id_0f1852be_fk_import_batch_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_record
    ADD CONSTRAINT import_record_import_batch_id_0f1852be_fk_import_batch_id FOREIGN KEY (import_batch_id) REFERENCES public.import_batch(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: inquiry inquiry_archived_by_employee_id_3c9f062f_fk_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inquiry
    ADD CONSTRAINT inquiry_archived_by_employee_id_3c9f062f_fk_employee_id FOREIGN KEY (archived_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: inquiry inquiry_customer_account_id_4643474e_fk_customer_account_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inquiry
    ADD CONSTRAINT inquiry_customer_account_id_4643474e_fk_customer_account_id FOREIGN KEY (customer_account_id) REFERENCES public.customer_account(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: inquiry inquiry_customer_contact_id_7f3aba57_fk_customer_contact_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inquiry
    ADD CONSTRAINT inquiry_customer_contact_id_7f3aba57_fk_customer_contact_id FOREIGN KEY (customer_contact_id) REFERENCES public.customer_contact(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: inquiry_file_link inquiry_file_link_business_file_id_bdca94b4_fk_business_file_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inquiry_file_link
    ADD CONSTRAINT inquiry_file_link_business_file_id_bdca94b4_fk_business_file_id FOREIGN KEY (business_file_id) REFERENCES public.business_file(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: inquiry_file_link inquiry_file_link_inquiry_id_94c95015_fk_inquiry_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inquiry_file_link
    ADD CONSTRAINT inquiry_file_link_inquiry_id_94c95015_fk_inquiry_id FOREIGN KEY (inquiry_id) REFERENCES public.inquiry(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: inquiry_item inquiry_item_inquiry_id_6d052293_fk_inquiry_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inquiry_item
    ADD CONSTRAINT inquiry_item_inquiry_id_6d052293_fk_inquiry_id FOREIGN KEY (inquiry_id) REFERENCES public.inquiry(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: inquiry inquiry_owner_employee_id_884aac17_fk_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inquiry
    ADD CONSTRAINT inquiry_owner_employee_id_884aac17_fk_employee_id FOREIGN KEY (owner_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: inquiry_sla_link inquiry_sla_link_inquiry_id_26597247_fk_inquiry_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inquiry_sla_link
    ADD CONSTRAINT inquiry_sla_link_inquiry_id_26597247_fk_inquiry_id FOREIGN KEY (inquiry_id) REFERENCES public.inquiry(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: inquiry_sla_link inquiry_sla_link_sla_tracking_id_c45ffc2b_fk_sla_tracking_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inquiry_sla_link
    ADD CONSTRAINT inquiry_sla_link_sla_tracking_id_c45ffc2b_fk_sla_tracking_id FOREIGN KEY (sla_tracking_id) REFERENCES public.sla_tracking(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: inquiry_task_link inquiry_task_link_business_task_id_8f84178c_fk_business_task_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inquiry_task_link
    ADD CONSTRAINT inquiry_task_link_business_task_id_8f84178c_fk_business_task_id FOREIGN KEY (business_task_id) REFERENCES public.business_task(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: inquiry_task_link inquiry_task_link_inquiry_id_826ba233_fk_inquiry_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inquiry_task_link
    ADD CONSTRAINT inquiry_task_link_inquiry_id_826ba233_fk_inquiry_id FOREIGN KEY (inquiry_id) REFERENCES public.inquiry(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: inquiry inquiry_transaction_entity_i_d46c6465_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inquiry
    ADD CONSTRAINT inquiry_transaction_entity_i_d46c6465_fk_customer_ FOREIGN KEY (transaction_entity_id) REFERENCES public.customer_transaction_entity(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: organization_unit organization_unit_archived_by_employee_70addc6d_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_unit
    ADD CONSTRAINT organization_unit_archived_by_employee_70addc6d_fk_employee_ FOREIGN KEY (archived_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: organization_unit organization_unit_parent_id_ce577442_fk_organization_unit_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organization_unit
    ADD CONSTRAINT organization_unit_parent_id_ce577442_fk_organization_unit_id FOREIGN KEY (parent_id) REFERENCES public.organization_unit(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation quotation_accepted_version_id_0b94ac2f_fk_quotation_version_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation
    ADD CONSTRAINT quotation_accepted_version_id_0b94ac2f_fk_quotation_version_id FOREIGN KEY (accepted_version_id) REFERENCES public.quotation_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation quotation_archived_by_employee_id_8134295a_fk_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation
    ADD CONSTRAINT quotation_archived_by_employee_id_8134295a_fk_employee_id FOREIGN KEY (archived_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation quotation_customer_account_id_3fd95a8b_fk_customer_account_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation
    ADD CONSTRAINT quotation_customer_account_id_3fd95a8b_fk_customer_account_id FOREIGN KEY (customer_account_id) REFERENCES public.customer_account(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation_dispatch_record quotation_dispatch_r_dispatched_by_employ_b4321a6d_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_dispatch_record
    ADD CONSTRAINT quotation_dispatch_r_dispatched_by_employ_b4321a6d_fk_employee_ FOREIGN KEY (dispatched_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation_dispatch_record quotation_dispatch_r_quotation_version_id_37c2c6d3_fk_quotation; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_dispatch_record
    ADD CONSTRAINT quotation_dispatch_r_quotation_version_id_37c2c6d3_fk_quotation FOREIGN KEY (quotation_version_id) REFERENCES public.quotation_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation_document quotation_document_business_file_id_dbf8483c_fk_business_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_document
    ADD CONSTRAINT quotation_document_business_file_id_dbf8483c_fk_business_ FOREIGN KEY (business_file_id) REFERENCES public.business_file(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation_document quotation_document_generated_by_employe_9679e780_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_document
    ADD CONSTRAINT quotation_document_generated_by_employe_9679e780_fk_employee_ FOREIGN KEY (generated_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation_document quotation_document_quotation_version_id_e9604550_fk_quotation; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_document
    ADD CONSTRAINT quotation_document_quotation_version_id_e9604550_fk_quotation FOREIGN KEY (quotation_version_id) REFERENCES public.quotation_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation_file_link quotation_file_link_business_file_id_fb42ab9d_fk_business_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_file_link
    ADD CONSTRAINT quotation_file_link_business_file_id_fb42ab9d_fk_business_ FOREIGN KEY (business_file_id) REFERENCES public.business_file(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation_file_link quotation_file_link_quotation_version_id_1ff93d38_fk_quotation; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_file_link
    ADD CONSTRAINT quotation_file_link_quotation_version_id_1ff93d38_fk_quotation FOREIGN KEY (quotation_version_id) REFERENCES public.quotation_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation_line quotation_line_quotation_version_id_e3757ba8_fk_quotation; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_line
    ADD CONSTRAINT quotation_line_quotation_version_id_e3757ba8_fk_quotation FOREIGN KEY (quotation_version_id) REFERENCES public.quotation_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation quotation_owner_employee_id_340b6e14_fk_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation
    ADD CONSTRAINT quotation_owner_employee_id_340b6e14_fk_employee_id FOREIGN KEY (owner_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation_quantity_tier quotation_quantity_t_quotation_line_id_b22f47bc_fk_quotation; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_quantity_tier
    ADD CONSTRAINT quotation_quantity_t_quotation_line_id_b22f47bc_fk_quotation FOREIGN KEY (quotation_line_id) REFERENCES public.quotation_line(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation quotation_source_inquiry_id_707a54cf_fk_inquiry_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation
    ADD CONSTRAINT quotation_source_inquiry_id_707a54cf_fk_inquiry_id FOREIGN KEY (source_inquiry_id) REFERENCES public.inquiry(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation_template quotation_template_archived_by_employee_04b5bed5_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_template
    ADD CONSTRAINT quotation_template_archived_by_employee_04b5bed5_fk_employee_ FOREIGN KEY (archived_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation quotation_transaction_entity_i_4918e8f1_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation
    ADD CONSTRAINT quotation_transaction_entity_i_4918e8f1_fk_customer_ FOREIGN KEY (transaction_entity_id) REFERENCES public.customer_transaction_entity(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation_version_approval_link quotation_version_ap_approval_request_id_96fe597b_fk_approval_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_version_approval_link
    ADD CONSTRAINT quotation_version_ap_approval_request_id_96fe597b_fk_approval_ FOREIGN KEY (approval_request_id) REFERENCES public.approval_request(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation_version_approval_link quotation_version_ap_quotation_version_id_fbcf23e0_fk_quotation; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_version_approval_link
    ADD CONSTRAINT quotation_version_ap_quotation_version_id_fbcf23e0_fk_quotation FOREIGN KEY (quotation_version_id) REFERENCES public.quotation_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation_version quotation_version_locked_by_employee_id_02d7baa2_fk_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_version
    ADD CONSTRAINT quotation_version_locked_by_employee_id_02d7baa2_fk_employee_id FOREIGN KEY (locked_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation_version quotation_version_quotation_id_66606047_fk_quotation_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_version
    ADD CONSTRAINT quotation_version_quotation_id_66606047_fk_quotation_id FOREIGN KEY (quotation_id) REFERENCES public.quotation(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation_version quotation_version_quotation_template_i_da27a219_fk_quotation; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_version
    ADD CONSTRAINT quotation_version_quotation_template_i_da27a219_fk_quotation FOREIGN KEY (quotation_template_id) REFERENCES public.quotation_template(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation_version_sla_link quotation_version_sl_quotation_version_id_cc010fde_fk_quotation; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_version_sla_link
    ADD CONSTRAINT quotation_version_sl_quotation_version_id_cc010fde_fk_quotation FOREIGN KEY (quotation_version_id) REFERENCES public.quotation_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation_version_sla_link quotation_version_sl_sla_tracking_id_e3e81a1d_fk_sla_track; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_version_sla_link
    ADD CONSTRAINT quotation_version_sl_sla_tracking_id_e3e81a1d_fk_sla_track FOREIGN KEY (sla_tracking_id) REFERENCES public.sla_tracking(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation_version_task_link quotation_version_ta_business_task_id_bd25ba77_fk_business_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_version_task_link
    ADD CONSTRAINT quotation_version_ta_business_task_id_bd25ba77_fk_business_ FOREIGN KEY (business_task_id) REFERENCES public.business_task(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: quotation_version_task_link quotation_version_ta_quotation_version_id_0b5f7e1c_fk_quotation; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quotation_version_task_link
    ADD CONSTRAINT quotation_version_ta_quotation_version_id_0b5f7e1c_fk_quotation FOREIGN KEY (quotation_version_id) REFERENCES public.quotation_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: reference_dictionary reference_dictionary_archived_by_employee_45e1a5d4_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.reference_dictionary
    ADD CONSTRAINT reference_dictionary_archived_by_employee_45e1a5d4_fk_employee_ FOREIGN KEY (archived_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: role_profile role_profile_archived_by_employee_id_b7931a63_fk_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_profile
    ADD CONSTRAINT role_profile_archived_by_employee_id_b7931a63_fk_employee_id FOREIGN KEY (archived_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: role_profile role_profile_auth_group_id_023213f2_fk_auth_group_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_profile
    ADD CONSTRAINT role_profile_auth_group_id_023213f2_fk_auth_group_id FOREIGN KEY (auth_group_id) REFERENCES public.auth_group(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_approval_link sample_approval_link_approval_request_id_401390f8_fk_approval_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_approval_link
    ADD CONSTRAINT sample_approval_link_approval_request_id_401390f8_fk_approval_ FOREIGN KEY (approval_request_id) REFERENCES public.approval_request(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_approval_link sample_approval_link_sample_request_id_f0d11809_fk_sample_re; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_approval_link
    ADD CONSTRAINT sample_approval_link_sample_request_id_f0d11809_fk_sample_re FOREIGN KEY (sample_request_id) REFERENCES public.sample_request(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_fee_record sample_fee_record_decided_by_employee__bf3bb4a8_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_fee_record
    ADD CONSTRAINT sample_fee_record_decided_by_employee__bf3bb4a8_fk_employee_ FOREIGN KEY (decided_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_fee_record sample_fee_record_sample_request_id_9662b953_fk_sample_re; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_fee_record
    ADD CONSTRAINT sample_fee_record_sample_request_id_9662b953_fk_sample_re FOREIGN KEY (sample_request_id) REFERENCES public.sample_request(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_feedback sample_feedback_customer_contact_id_87d5966b_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_feedback
    ADD CONSTRAINT sample_feedback_customer_contact_id_87d5966b_fk_customer_ FOREIGN KEY (customer_contact_id) REFERENCES public.customer_contact(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_feedback sample_feedback_recorded_by_employee_id_b85309b4_fk_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_feedback
    ADD CONSTRAINT sample_feedback_recorded_by_employee_id_b85309b4_fk_employee_id FOREIGN KEY (recorded_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_feedback sample_feedback_sample_request_id_c8308873_fk_sample_request_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_feedback
    ADD CONSTRAINT sample_feedback_sample_request_id_c8308873_fk_sample_request_id FOREIGN KEY (sample_request_id) REFERENCES public.sample_request(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_file_link sample_file_link_business_file_id_8b7fe3f8_fk_business_file_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_file_link
    ADD CONSTRAINT sample_file_link_business_file_id_8b7fe3f8_fk_business_file_id FOREIGN KEY (business_file_id) REFERENCES public.business_file(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_file_link sample_file_link_sample_request_id_108b58ee_fk_sample_re; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_file_link
    ADD CONSTRAINT sample_file_link_sample_request_id_108b58ee_fk_sample_re FOREIGN KEY (sample_request_id) REFERENCES public.sample_request(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_item sample_item_sample_request_id_e21ad888_fk_sample_request_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_item
    ADD CONSTRAINT sample_item_sample_request_id_e21ad888_fk_sample_request_id FOREIGN KEY (sample_request_id) REFERENCES public.sample_request(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_request sample_request_archived_by_employee_id_e485ab75_fk_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_request
    ADD CONSTRAINT sample_request_archived_by_employee_id_e485ab75_fk_employee_id FOREIGN KEY (archived_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_request sample_request_customer_account_id_7f3f13f0_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_request
    ADD CONSTRAINT sample_request_customer_account_id_7f3f13f0_fk_customer_ FOREIGN KEY (customer_account_id) REFERENCES public.customer_account(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_request sample_request_customer_contact_id_8b8b27a5_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_request
    ADD CONSTRAINT sample_request_customer_contact_id_8b8b27a5_fk_customer_ FOREIGN KEY (customer_contact_id) REFERENCES public.customer_contact(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_request sample_request_owner_employee_id_7e050fae_fk_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_request
    ADD CONSTRAINT sample_request_owner_employee_id_7e050fae_fk_employee_id FOREIGN KEY (owner_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_request sample_request_source_inquiry_id_8e52ce29_fk_inquiry_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_request
    ADD CONSTRAINT sample_request_source_inquiry_id_8e52ce29_fk_inquiry_id FOREIGN KEY (source_inquiry_id) REFERENCES public.inquiry(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_request sample_request_source_quotation_ver_0d70c589_fk_quotation; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_request
    ADD CONSTRAINT sample_request_source_quotation_ver_0d70c589_fk_quotation FOREIGN KEY (source_quotation_version_id) REFERENCES public.quotation_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_request sample_request_transaction_entity_i_f6126e8c_fk_customer_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_request
    ADD CONSTRAINT sample_request_transaction_entity_i_f6126e8c_fk_customer_ FOREIGN KEY (transaction_entity_id) REFERENCES public.customer_transaction_entity(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_shipment sample_shipment_fee_warning_acknowle_1e536815_fk_employee_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_shipment
    ADD CONSTRAINT sample_shipment_fee_warning_acknowle_1e536815_fk_employee_ FOREIGN KEY (fee_warning_acknowledged_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_shipment_item sample_shipment_item_sample_item_id_ce7acb07_fk_sample_item_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_shipment_item
    ADD CONSTRAINT sample_shipment_item_sample_item_id_ce7acb07_fk_sample_item_id FOREIGN KEY (sample_item_id) REFERENCES public.sample_item(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_shipment_item sample_shipment_item_sample_shipment_id_dbd71529_fk_sample_sh; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_shipment_item
    ADD CONSTRAINT sample_shipment_item_sample_shipment_id_dbd71529_fk_sample_sh FOREIGN KEY (sample_shipment_id) REFERENCES public.sample_shipment(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_shipment sample_shipment_sample_request_id_45fbecbe_fk_sample_request_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_shipment
    ADD CONSTRAINT sample_shipment_sample_request_id_45fbecbe_fk_sample_request_id FOREIGN KEY (sample_request_id) REFERENCES public.sample_request(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_shipment sample_shipment_shipped_by_employee_id_19bdee0f_fk_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_shipment
    ADD CONSTRAINT sample_shipment_shipped_by_employee_id_19bdee0f_fk_employee_id FOREIGN KEY (shipped_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_sla_link sample_sla_link_sample_request_id_05764df3_fk_sample_request_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_sla_link
    ADD CONSTRAINT sample_sla_link_sample_request_id_05764df3_fk_sample_request_id FOREIGN KEY (sample_request_id) REFERENCES public.sample_request(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_sla_link sample_sla_link_sla_tracking_id_93c9f7ce_fk_sla_tracking_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_sla_link
    ADD CONSTRAINT sample_sla_link_sla_tracking_id_93c9f7ce_fk_sla_tracking_id FOREIGN KEY (sla_tracking_id) REFERENCES public.sla_tracking(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_task_link sample_task_link_business_task_id_e25c4d49_fk_business_task_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_task_link
    ADD CONSTRAINT sample_task_link_business_task_id_e25c4d49_fk_business_task_id FOREIGN KEY (business_task_id) REFERENCES public.business_task(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sample_task_link sample_task_link_sample_request_id_508894f2_fk_sample_re; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sample_task_link
    ADD CONSTRAINT sample_task_link_sample_request_id_508894f2_fk_sample_re FOREIGN KEY (sample_request_id) REFERENCES public.sample_request(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: saved_view saved_view_archived_by_employee_id_86f69b95_fk_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.saved_view
    ADD CONSTRAINT saved_view_archived_by_employee_id_86f69b95_fk_employee_id FOREIGN KEY (archived_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: saved_view saved_view_employee_id_ed85d6be_fk_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.saved_view
    ADD CONSTRAINT saved_view_employee_id_ed85d6be_fk_employee_id FOREIGN KEY (employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sla_policy sla_policy_archived_by_employee_id_85953882_fk_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sla_policy
    ADD CONSTRAINT sla_policy_archived_by_employee_id_85953882_fk_employee_id FOREIGN KEY (archived_by_employee_id) REFERENCES public.employee(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sla_tracking sla_tracking_sla_policy_id_51aa403c_fk_sla_policy_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sla_tracking
    ADD CONSTRAINT sla_tracking_sla_policy_id_51aa403c_fk_sla_policy_id FOREIGN KEY (sla_policy_id) REFERENCES public.sla_policy(id) DEFERRABLE INITIALLY DEFERRED;


--
-- PostgreSQL database dump complete
--

\unrestrict BAqEVkDBc9MKXpLGwxOla8WTC3UbEYIHA6jsvHVCK9XCQ8T5H8wugpCBWU4H5gQ

