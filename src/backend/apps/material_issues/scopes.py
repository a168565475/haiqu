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
    "CUTTING": frozenset({"FABRIC"}),
    "SEWING": frozenset({"AUXILIARY"}),
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


def material_section_codes_for_issue(issue):
    plan_category = getattr(issue, "_material_issue_plan_category", "")
    if not plan_category and issue.pk:
        snapshot = issue.audit_events.filter(action="CREATED").order_by("created_at", "id").values_list("snapshot", flat=True).first() or {}
        plan_category = (snapshot.get("plan_source") or {}).get("plan_category", "")
    return material_section_codes_for_workshop(issue.workshop.name if issue.workshop_id else "", plan_category)


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
