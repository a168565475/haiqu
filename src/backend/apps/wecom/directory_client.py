"""员工通讯录只读来源；不创建员工、账号、绑定，也不推断 ERP 在职状态。"""
from django.views.decorators.debug import sensitive_variables

from .client import WeComClient, WeComError, _check_result, _error, _valid_text
from . import directory_progress


MEMBER_STATUS_LABELS = {1: "已激活", 2: "已禁用", 4: "未激活", 5: "退出企业"}


def _source_error():
    return WeComError("INVALID_DIRECTORY_DATA", "企业微信通讯录字段不完整或格式异常，本次读取未完成。")


def _scope_error():
    return WeComError("DIRECTORY_SCOPE_INCOMPLETE", "无法确认企业微信全员及部门范围，请核对应用可见范围后重试。")


def _uint32(value, minimum=0):
    return type(value) is int and minimum <= value < 2 ** 32


@sensitive_variables()
def _rows(result, field):
    rows = result.get(field)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise _source_error()
    return rows


@sensitive_variables()
def _member(row):
    user_id = row.get("userid")
    name = row.get("name", "")
    departments = row.get("department")
    status = row.get("status")
    primary = row.get("main_department")
    if (
        not _valid_text(user_id, 64) or user_id != user_id.strip()
        or not (name == "" or _valid_text(name, 256))
        or not isinstance(departments, list) or not departments
        or any(not _uint32(value, 1) for value in departments)
    ):
        raise _source_error()
    if len(set(departments)) != len(departments):
        raise _source_error()
    if status is not None and not _uint32(status):
        raise _source_error()
    if primary is not None and (not _uint32(primary, 1) or primary not in departments):
        raise _source_error()
    # 缺失姓名、主部门和状态保持未知；不补造名称，不取第一个部门作为主部门。
    return {"userid": user_id, "name": name.strip(), "department": sorted(departments),
            "main_department": primary, "status": status,
            "status_label": MEMBER_STATUS_LABELS.get(status, "未知")}


class WeComDirectoryClient(WeComClient):
    """复用现有凭据、限时请求、禁重定向和脱敏错误边界。"""

    @sensitive_variables()
    def require_full_scope(self):
        result = self._authenticated_get("agent/get", {"agentid": self.agent_id})
        _check_result(result)
        if type(result.get("agentid")) is not int or result["agentid"] != self.agent_id:
            raise _error("CONFIGURATION_ERROR")
        if "close" in result and (type(result["close"]) is not int or result["close"] != 0):
            raise _error("CONFIGURATION_ERROR")
        parties = result.get("allow_partys")
        if not isinstance(parties, dict) or not isinstance(parties.get("partyid"), list):
            raise _scope_error()
        ids = parties["partyid"]
        if any(not _uint32(value, 1) for value in ids) or 1 not in ids:
            raise _scope_error()

    @sensitive_variables()
    def get_departments(self):
        # 先取得稳定 ID，再补单部门名称，不改变现有考勤的 simplelist 契约。
        # https://developer.work.weixin.qq.com/document/path/95350
        # https://developer.work.weixin.qq.com/document/path/95351
        result = self._authenticated_get("department/simplelist", {})
        _check_result(result)
        departments = {}
        for row in _rows(result, "department_id"):
            department_id, parent_id = row.get("id"), row.get("parentid")
            if not _uint32(department_id, 1) or not _uint32(parent_id) or department_id in departments:
                raise _source_error()
            departments[department_id] = {"id": department_id, "parentid": parent_id}
        if 1 not in departments or departments[1]["parentid"] != 0:
            raise _scope_error()
        # 父部门缺失或循环时不能给后续部门映射提供一棵残缺的组织树。
        for department_id in departments:
            seen = set()
            current = department_id
            while current != 1:
                if current not in departments or current in seen:
                    raise _scope_error()
                seen.add(current)
                current = departments[current]["parentid"]
        # 已取得完整部门数，才确定总工作量；随后按真实上游响应推进。
        directory_progress.add_work(len(departments) * 2 + 2)
        directory_progress.advance("读取部门详情", 2)
        for department_id, department in departments.items():
            result = self._authenticated_get("department/get", {"id": department_id})
            _check_result(result)
            detail = result.get("department")
            if (
                not isinstance(detail, dict) or type(detail.get("id")) is not int
                or detail["id"] != department_id or type(detail.get("parentid")) is not int
                or detail["parentid"] != department["parentid"] or not _valid_text(detail.get("name"), 768)
            ):
                raise _source_error()
            department["name"] = detail["name"].strip()
            directory_progress.advance("读取部门详情")
        return sorted(departments.values(), key=lambda department: department["id"])

    @sensitive_variables()
    def get_department_members(self, department_id):
        if not _uint32(department_id, 1):
            raise WeComError("DIRECTORY_REQUEST_INVALID", "部门 ID 必须为有效的正整数。", 400)
        # 逐部门读取详情；不依赖已废弃的递归子部门参数。
        # https://developer.work.weixin.qq.com/document/path/90201
        result = self._authenticated_get("user/list", {"department_id": department_id})
        _check_result(result)
        members = []
        seen = set()
        for row in _rows(result, "userlist"):
            member = _member(row)
            if department_id not in member["department"] or member["userid"].lower() in seen:
                raise _source_error()
            seen.add(member["userid"].lower())
            members.append(member)
        return members

    @sensitive_variables()
    def read_directory(self):
        """完整读取成功后才返回；上游失败不交付部分名单，也不保存业务数据。"""
        self.require_full_scope()
        departments = self.get_departments()
        department_ids = {department["id"] for department in departments}
        members = {}
        observed_departments = {}
        for department in departments:
            for member in self.get_department_members(department["id"]):
                if not set(member["department"]).issubset(department_ids):
                    raise _scope_error()
                key = member["userid"].lower()
                previous = members.get(key)
                if previous is not None:
                    # 同一人跨部门可重复返回；资料冲突时不能静默使用先读或后读的那份。
                    if {**previous, "userid": key} != {**member, "userid": key}:
                        raise WeComError("DIRECTORY_CHANGED", "读取期间成员资料不一致，请重新读取后再核对。")
                else:
                    members[key] = member
                    observed_departments[key] = set()
                observed_departments[key].add(department["id"])
            directory_progress.advance("读取部门员工")
        if not members:
            raise WeComError("EMPTY_DIRECTORY", "企业微信未返回成员，本次读取未完成，不能据此停用或删除员工。")
        for key, member in members.items():
            if observed_departments[key] != set(member["department"]):
                raise WeComError("DIRECTORY_CHANGED", "成员所属部门与部门名单不一致，请重新读取后再核对。")
        return {"corp_id": self.corp_id, "departments": departments,
                "members": sorted(members.values(), key=lambda member: member["userid"].lower())}
