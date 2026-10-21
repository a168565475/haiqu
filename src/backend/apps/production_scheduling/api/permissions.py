from rest_framework.permissions import BasePermission

from apps.access_control import module_policy


class ScheduleCompletePermission(BasePermission):
    message = "当前账号没有完成生产任务的权限。"

    def has_permission(self, request, view):
        return module_policy.has_operation(
            request, "access_control.finish_productiontask", "production_tasks.change_productiontask",
        )
