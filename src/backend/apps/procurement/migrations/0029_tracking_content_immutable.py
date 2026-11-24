from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('procurement', '0028_purchasetrackingdigest_purchasetrackingissue_and_more')]

    operations = [migrations.RunSQL(
        sql="""
            CREATE OR REPLACE FUNCTION procurement_tracking_content_immutable() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'purchase tracking content is append only';
            END;
            $$ LANGUAGE plpgsql;
            DROP TRIGGER IF EXISTS procurement_tracking_content_immutable ON procurement_tracking_content;
            CREATE TRIGGER procurement_tracking_content_immutable
            BEFORE UPDATE OR DELETE ON procurement_tracking_content
            FOR EACH ROW EXECUTE FUNCTION procurement_tracking_content_immutable();
        """,
        reverse_sql="""
            DROP TRIGGER procurement_tracking_content_immutable ON procurement_tracking_content;
            DROP FUNCTION procurement_tracking_content_immutable();
        """,
    )]
