import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q


TYPE_NAMESPACE = uuid.UUID("482162ba-d1fa-47ca-a738-5c74ea651906")

LANGUAGE_OPTIONS = [
    ("EN", "English", 10),
    ("ZH_CN", "简体中文", 20),
    ("DE", "Deutsch", 30),
    ("ES", "Español", 40),
    ("FR", "Français", 50),
]

TIMEZONE_OPTIONS = [
    ("ASIA_SHANGHAI", "中国标准时间", "Asia/Shanghai", 10),
    ("EUROPE_BERLIN", "中欧时间", "Europe/Berlin", 20),
    ("EUROPE_LONDON", "英国时间", "Europe/London", 30),
    ("AMERICA_NEW_YORK", "美国东部时间", "America/New_York", 40),
    ("AMERICA_LOS_ANGELES", "美国太平洋时间", "America/Los_Angeles", 50),
]


def seed_contact_options_and_history(apps, schema_editor):
    ReferenceDictionary = apps.get_model("reference_data", "ReferenceDictionary")
    DictionaryType = apps.get_model("reference_data", "DictionaryType")
    CustomerContact = apps.get_model("customers", "CustomerContact")
    EmploymentEvent = apps.get_model("customers", "CustomerContactEmploymentEvent")

    language_type, _created = DictionaryType.objects.get_or_create(
        code="CONTACT_LANGUAGE",
        defaults={
            "id": uuid.uuid5(TYPE_NAMESPACE, "CONTACT_LANGUAGE"),
            "chinese_name": "联系人语言",
            "english_name": "Contact Language",
            "group_code": "CONTACT",
            "status": "ACTIVE",
            "sort_order": 40,
            "description": "联系人语言字典。",
        },
    )
    timezone_type, _created = DictionaryType.objects.get_or_create(
        code="CONTACT_TIMEZONE",
        defaults={
            "id": uuid.uuid5(TYPE_NAMESPACE, "CONTACT_TIMEZONE"),
            "chinese_name": "联系人时区",
            "english_name": "Contact Timezone",
            "group_code": "CONTACT",
            "status": "ACTIVE",
            "sort_order": 50,
            "description": "联系人时区字典。",
        },
    )

    for item_code, display_name, sort_order in LANGUAGE_OPTIONS:
        ReferenceDictionary.objects.update_or_create(
            category_code="CONTACT_LANGUAGE",
            item_code=item_code,
            defaults={
                "dictionary_type": language_type,
                "display_name": display_name,
                "description": "联系人首选沟通语言",
                "status": "ACTIVE",
                "sort_order": sort_order,
                "extra_data": {},
            },
        )
    for item_code, display_name, timezone_code, sort_order in TIMEZONE_OPTIONS:
        ReferenceDictionary.objects.update_or_create(
            category_code="CONTACT_TIMEZONE",
            item_code=item_code,
            defaults={
                "dictionary_type": timezone_type,
                "display_name": display_name,
                "description": "联系人所在时区",
                "status": "ACTIVE",
                "sort_order": sort_order,
                "extra_data": {"timezone_code": timezone_code},
            },
        )

    for contact in CustomerContact.objects.filter(archived_at__isnull=True).iterator():
        EmploymentEvent.objects.get_or_create(
            customer_contact_id=contact.pk,
            event_type="JOINED",
            effective_on=contact.created_at.date(),
            defaults={
                "title": "导入现有任职记录",
                "position_title": contact.position_title,
                "department_name": contact.department_name,
                "role_types": [],
                "is_primary_contact": contact.is_primary_contact,
                "notes": "CUS-05 数据迁移生成的初始任职快照。",
                "change_data": {"source": "MIGRATION"},
            },
        )


def unseed_contact_options(apps, schema_editor):
    ReferenceDictionary = apps.get_model("reference_data", "ReferenceDictionary")
    ReferenceDictionary.objects.filter(
        category_code__in=["CONTACT_LANGUAGE", "CONTACT_TIMEZONE"],
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("customers", "0005_contact_module_foundation"),
        ("reference_data", "0007_exchangerate_incoterm_paymentmethod_port_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="customercontact",
            name="department_name",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="customercontact",
            name="english_name",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="customercontact",
            name="is_primary_contact",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="customercontact",
            name="left_effective_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="customercontact",
            name="marketing_opt_out",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="customercontact",
            name="marketing_opt_out_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="customercontact",
            name="marketing_opt_out_by_employee",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="marketing_opt_out_contacts",
                to="organizations.employee",
            ),
        ),
        migrations.AddField(
            model_name="customercontact",
            name="preferred_language_code",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="customercontact",
            name="timezone_code",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddConstraint(
            model_name="customercontact",
            constraint=models.CheckConstraint(
                condition=Q(left_effective_date__isnull=True) | Q(status="LEFT"),
                name="contact_left_date_requires_left",
            ),
        ),
        migrations.AddConstraint(
            model_name="customercontact",
            constraint=models.UniqueConstraint(
                condition=Q(archived_at__isnull=True, is_primary_contact=True, status="ACTIVE"),
                fields=("customer_account",),
                name="contact_active_primary_uniq",
            ),
        ),
        migrations.CreateModel(
            name="CustomerContactEmploymentEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("event_type", models.CharField(choices=[("JOINED", "加入客户公司"), ("PROFILE_CHANGED", "任职资料变更"), ("PRIMARY_CHANGED", "主要联系人变更"), ("LEFT", "离职")], max_length=30)),
                ("effective_on", models.DateField()),
                ("title", models.CharField(max_length=250)),
                ("position_title", models.CharField(blank=True, max_length=150)),
                ("department_name", models.CharField(blank=True, max_length=150)),
                ("role_types", models.JSONField(blank=True, default=list)),
                ("is_primary_contact", models.BooleanField(default=False)),
                ("notes", models.TextField(blank=True)),
                ("change_data", models.JSONField(blank=True, default=dict)),
                ("actor_employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="contact_employment_events_created", to="organizations.employee")),
                ("customer_contact", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="employment_events", to="customers.customercontact")),
            ],
            options={
                "db_table": "customer_contact_employment_event",
                "indexes": [models.Index(fields=["customer_contact", "-effective_on", "-created_at", "-id"], name="contact_employment_history_idx")],
                "constraints": [models.CheckConstraint(condition=Q(event_type__in=["JOINED", "PROFILE_CHANGED", "PRIMARY_CHANGED", "LEFT"]), name="contact_employment_event_type_valid")],
            },
        ),
        migrations.CreateModel(
            name="CustomerContactTaskLink",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("business_task", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="contact_links", to="workflow.businesstask")),
                ("customer_contact", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="task_links", to="customers.customercontact")),
            ],
            options={
                "db_table": "customer_contact_task_link",
                "indexes": [models.Index(fields=["customer_contact", "business_task"], name="contact_task_lookup_idx")],
                "constraints": [models.UniqueConstraint(fields=("customer_contact", "business_task"), name="customer_contact_task_link_uniq")],
            },
        ),
        migrations.RunPython(seed_contact_options_and_history, unseed_contact_options),
    ]
