from decimal import Decimal


WORKSHOP_MATERIAL_SECTION_CODES = {
    "金工车间": frozenset({"PROFILE", "HARDWARE", "PLASTIC", "SEMI"}),
    "车缝车间": frozenset({"FABRIC", "AUXILIARY", "SEMI"}),
    "装配车间": frozenset({"PACKAGING", "SEMI"}),
}

PLAN_WORKSHOP_NAMES = {
    "METAL": "金工车间",
    "CUTTING": "车缝车间",
    "SEWING": "车缝车间",
    "ASSEMBLY": "装配车间",
}

PLAN_MATERIAL_SECTION_CODES = {
    "METAL": frozenset({"PROFILE", "HARDWARE"}),
    "CUTTING": frozenset({"FABRIC", "AUXILIARY"}),
    "SEWING": frozenset({"AUXILIARY", "SEMI"}),
    "ASSEMBLY": frozenset({"PROFILE", "HARDWARE", "PLASTIC", "AUXILIARY", "PACKAGING", "SEMI"}),
}


def material_section_codes_for_workshop(workshop_name, plan_category=None):
    workshop_name = (workshop_name or "").strip()
    plan_category = (plan_category or "").strip().upper()
    if plan_category:
        if PLAN_WORKSHOP_NAMES.get(plan_category) != workshop_name:
            return None
        return PLAN_MATERIAL_SECTION_CODES.get(plan_category)
    return WORKSHOP_MATERIAL_SECTION_CODES.get(workshop_name)


def issue_plan_category(issue):
    plan_category = getattr(issue, "_material_issue_plan_category", "")
    if not plan_category and issue.pk:
        snapshot = issue.audit_events.filter(action="CREATED").order_by("created_at", "id").values_list("snapshot", flat=True).first() or {}
        plan_category = (snapshot.get("plan_source") or {}).get("plan_category", "")
    return plan_category


def semi_plan_category(workshop_name, plan_category=None):
    return (plan_category or "").strip().upper() or {
        '装配车间': 'ASSEMBLY', '车缝车间': 'SEWING', '金工车间': 'METAL',
    }.get(workshop_name, '')


def visible_new_issue_requirements(rows, plan_category):
    raw_section = {"ASSEMBLY": "PROFILE", "CUTTING": "FABRIC"}.get(plan_category)
    if not raw_section:
        return rows
    return [
        row for row in rows
        if row["line_type"] != "RAW" or row["section_code"] != raw_section
        or Decimal(row["max_issue_quantity"]) > 0
    ]


def material_section_codes_for_issue(issue):
    return material_section_codes_for_workshop(issue.workshop.name if issue.workshop_id else "", issue_plan_category(issue))


def cutting_source_line_ids(product_id):
    from apps.boms.models import Bom, BomLine
    bom = Bom.objects.filter(product_line_id=product_id, archived_at__isnull=True).order_by('-version_number', '-id').first()
    return set(BomLine.objects.filter(section__bom=bom, component_kind='CUT_PIECE',
        fabric_source_line__isnull=False).values_list('fabric_source_line_id', flat=True)) if bom else set()


def raw_line_allowed_for_plan(line_id, section_code, plan_category, cutting_sources):
    if not cutting_sources:
        return True
    if plan_category == 'CUTTING':
        return section_code != 'AUXILIARY' or line_id in cutting_sources
    return line_id not in cutting_sources


def raw_requirement_allowed_for_issue(issue, requirement):
    sources = cutting_source_line_ids(issue.product_line_id)
    category = semi_plan_category(issue.workshop.name, issue_plan_category(issue))
    return any(raw_line_allowed_for_plan(line_id, requirement.section_code, category, sources)
        for line_id in requirement.contributions.filter(is_current=True,
            product_line_id=issue.product_line_id).values_list('bom_line_id', flat=True))


def filter_blockers_for_scope(blockers, *, product_line_id, section_codes):
    product_line_id = str(product_line_id)
    return [
        blocker
        for blocker in blockers
        if (
            (not blocker.get("product_line_id") or blocker["product_line_id"] == product_line_id)
            and (not blocker.get("section_code") or blocker["section_code"] in section_codes)
        )
    ]
