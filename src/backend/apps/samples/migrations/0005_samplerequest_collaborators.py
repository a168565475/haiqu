# Django needs this state migration for the explicit through relation created in 0004.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0001_initial"),
        ("samples", "0004_sam02_detail_fields_and_collaborators"),
    ]

    operations = [
        migrations.AddField(
            model_name="samplerequest",
            name="collaborators",
            field=models.ManyToManyField(
                blank=True,
                related_name="collaborated_sample_requests",
                through="samples.SampleCollaborator",
                to="organizations.employee",
            ),
        ),
    ]
