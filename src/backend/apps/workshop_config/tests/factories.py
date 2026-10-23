from datetime import timedelta
from uuid import uuid4

from django.utils import timezone

from apps.organizations.models import Employee, EmployeeOrganizationAssignment, OrganizationUnit


def production_employee(*, workshop, position, name, is_supervisor=False, status="ACTIVE", employee=None, **unused):
    person = employee or Employee.objects.create(employee_code=f"TEST_{uuid4().hex.upper()}", display_name=name)
    person.workshop = workshop
    person.workshop_position = position
    person.workshop_is_supervisor = is_supervisor
    person.workshop_status = status
    person.save()
    department, _ = OrganizationUnit.objects.get_or_create(unit_code="DEPT_PRODUCTION", defaults={"unit_name": "生产部"})
    if not person.organization_assignments.filter(organization_unit=department).exists():
        EmployeeOrganizationAssignment.objects.create(employee=person, organization_unit=department, effective_from=timezone.now()-timedelta(days=1))
    return person
