import json
from datetime import datetime, time
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request
from zoneinfo import ZoneInfo

from django.views.decorators.debug import sensitive_variables

from apps.wecom.client import WeComClient, WeComError, _check_result, _error, _valid_text
from .source import normalize_supplements


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _uint32(value, minimum=0):
    return type(value) is int and minimum <= value < 2 ** 32


@sensitive_variables()
def _array(container, field):
    value = container.get(field)
    if not isinstance(value, list):
        raise _error()
    return value


@sensitive_variables()
def _id_array(container, field):
    values = _array(container, field)
    if any(not _uint32(value, 1) for value in values):
        raise _error()
    return values


@sensitive_variables()
def _object_array(container, field):
    values = _array(container, field)
    if any(not isinstance(value, dict) for value in values):
        raise _error()
    return values


@sensitive_variables()
def _text(value, max_bytes=512):
    # 名称等来源字段允许明确空串；成员账号另行要求非空。
    return value == "" or _valid_text(value, max_bytes)


def _invalid_request():
    return WeComError("ATTENDANCE_REQUEST_INVALID", "考勤查询参数无效，请检查成员和时间范围。", 400)


def _check_attendance_result(result):
    if result["errcode"] == 301062:
        raise WeComError("VACATION_PERMISSION_DENIED", "应用没有假期读取权限，请在企业微信审批的可调用接口应用中授权。")
    if result["errcode"] == 301063:
        raise WeComError("VACATION_REQUEST_REJECTED", "企业微信拒绝了假期查询参数，请核对成员可见范围及假期配置。")
    _check_result(result)


def _vacation_rows(result):
    _check_attendance_result(result)
    rows = _object_array(result, "lists")
    ids = [row.get("id") for row in rows]
    if any(not _uint32(value, 1) for value in ids) or len(set(ids)) != len(ids):
        raise _error()
    return rows


def _optional_quota_number(row, field):
    value = row.get(field)
    if value is not None and not _uint32(value):
        raise _error()
    return value


def _optional_quota_name(row, field):
    value = row.get(field)
    if value is not None and not _text(value, 1000):
        raise _error()
    return value


class AttendanceClient(WeComClient):
    """企业微信只读考勤接口；凭据、缓存及 GET 安全策略沿用 WeComClient。"""

    @sensitive_variables()
    def _post_read(self, endpoint, token, payload):
        request = Request(
            self.API_BASE_URL + endpoint + "?" + urlencode({"access_token": token}),
            data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=self.TIMEOUT_SECONDS) as response:
                if response.status != 200:
                    raise _error()
                body = response.read(self.MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            error.close()
            raise _error() from None
        except (URLError, OSError, HTTPException):
            raise _error() from None
        if len(body) > self.MAX_RESPONSE_BYTES:
            raise _error()
        try:
            result = json.loads(body.decode("utf-8"))
        except (UnicodeError, ValueError):
            raise _error() from None
        if not isinstance(result, dict) or type(result.get("errcode")) is not int:
            raise _error()
        return result

    @sensitive_variables()
    def _authenticated_read(self, endpoint, payload):
        token = self._access_token()
        result = self._post_read(endpoint, token, payload)
        # 这些 POST 仅查询数据；仅明确 token 失效允许重发，网络失败留待下一有界步骤。
        if result["errcode"] in (40014, 42001):
            token = self._access_token(rejected_token=token)
            result = self._post_read(endpoint, token, payload)
        _check_attendance_result(result)
        return result

    @sensitive_variables()
    def get_scope(self):
        # https://developer.work.weixin.qq.com/document/path/90227
        result = self._authenticated_get("agent/get", {"agentid": self.agent_id})
        _check_result(result)
        if type(result.get("agentid")) is not int or result["agentid"] != self.agent_id:
            raise _error("CONFIGURATION_ERROR")
        if "close" in result and (type(result["close"]) is not int or result["close"] != 0):
            raise _error("CONFIGURATION_ERROR")
        if not isinstance(result.get("allow_partys"), dict):
            raise _error()
        scope = {"allow_partys": {"partyid": _id_array(result["allow_partys"], "partyid")}}
        # 全员证明只用明确根部门；可选范围缺省时不补造空数组。
        for field in ("allow_userinfos", "allow_tags"):
            if field in result and not isinstance(result[field], dict):
                raise _error()
        if "allow_userinfos" in result:
            users = _object_array(result["allow_userinfos"], "user")
            if any(not _valid_text(user.get("userid"), 64) for user in users):
                raise _error()
            scope["allow_userinfos"] = {"user": [{"userid": user["userid"]} for user in users]}
        if "allow_tags" in result:
            scope["allow_tags"] = {"tagid": _id_array(result["allow_tags"], "tagid")}
        return scope

    @sensitive_variables()
    def get_departments(self):
        # https://developer.work.weixin.qq.com/document/path/95350
        result = self._authenticated_get("department/simplelist", {})
        _check_result(result)
        departments = _object_array(result, "department_id")
        if any(not _uint32(item.get("id"), 1) or not _uint32(item.get("parentid")) for item in departments):
            raise _error()
        return [{"id": item["id"], "parentid": item["parentid"]} for item in departments]

    @sensitive_variables()
    def get_department_members(self, department_id):
        # https://developer.work.weixin.qq.com/document/path/90200：单部门，子部门由服务层遍历。
        if not _uint32(department_id, 1):
            raise _invalid_request()
        result = self._authenticated_get("user/simplelist", {"department_id": department_id})
        _check_result(result)
        members = []
        for item in _object_array(result, "userlist"):
            if not _valid_text(item.get("userid"), 64) or not _text(item.get("name", ""), 256):
                raise _error()
            departments = _id_array(item, "department")
            members.append({"userid": item["userid"], "name": item.get("name", ""), "department": departments})
        return members

    @sensitive_variables()
    def get_tag_members(self, tag_id):
        # https://developer.work.weixin.qq.com/document/path/90213
        if not _uint32(tag_id, 1):
            raise _invalid_request()
        result = self._authenticated_get("tag/get", {"tagid": tag_id})
        _check_result(result)
        users = []
        for item in _object_array(result, "userlist"):
            if not _valid_text(item.get("userid"), 64) or not _text(item.get("name", ""), 256):
                raise _error()
            users.append({"userid": item["userid"], "name": item.get("name", "")})
        return {"users": users, "departments": _id_array(result, "partylist")}

    @sensitive_variables()
    def get_records(self, kind, starttime, endtime, userids):
        # 官方文档：raw 90262、daily 93374、monthly 93387。
        endpoints = {"raw": "getcheckindata", "daily": "getcheckin_daydata", "monthly": "getcheckin_monthdata"}
        if (
            not isinstance(kind, str) or kind not in endpoints
            or not _uint32(starttime) or not _uint32(endtime) or endtime < starttime
            or not isinstance(userids, list) or not 1 <= len(userids) <= 100
            or any(not _valid_text(user_id, 64) for user_id in userids)
        ):
            raise _invalid_request()
        if kind == "raw":
            if endtime - starttime > 30 * 86400:
                raise _invalid_request()
        elif any(datetime.fromtimestamp(value, SHANGHAI).time() != time.min for value in (starttime, endtime)):
            raise _invalid_request()
        payload = {"starttime": starttime, "endtime": endtime, "useridlist": userids}
        if kind == "raw":
            payload["opencheckindatatype"] = 3
        result = self._authenticated_read("checkin/" + endpoints[kind], payload)
        records = _object_array(result, "checkindata" if kind == "raw" else "datas")
        allowed = {user_id.lower() for user_id in userids}
        for row in records:
            self._validate_record(kind, row, allowed)
        # 只交给内部服务做白名单归一化；不得把原始响应写日志或直接返回 API。
        return records

    @sensitive_variables()
    def _validate_record(self, kind, row, allowed):
        if kind == "raw":
            if not _valid_text(row.get("userid"), 64) or row["userid"].lower() not in allowed:
                raise _error()
            if not _uint32(row.get("checkin_time")):
                raise _error()
            for field in ("checkin_type", "exception_type", "groupname"):
                if field in row and not _text(row[field], 2048):
                    raise _error()
            return
        base = row.get("base_info")
        if not isinstance(base, dict) or not _valid_text(base.get("acctid"), 64) or base["acctid"].lower() not in allowed:
            raise _error()
        if kind == "daily" and not _uint32(base.get("date")):
            raise _error()
        for field in ("name", "departs_name"):
            if field in base and not _text(base[field], 4096):
                raise _error()
        if "day_type" in base and (type(base["day_type"]) is not int or base["day_type"] not in (0, 1)):
            raise _error()
        if "rule_info" in base:
            rule = base["rule_info"]
            if not isinstance(rule, dict):
                raise _error()
            for field in ("groupname", "schedulename"):
                if field in rule and not _text(rule[field]):
                    raise _error()
            if "checkintime" in rule:
                for times in _object_array(rule, "checkintime"):
                    if not _uint32(times.get("work_sec")) or not _uint32(times.get("off_work_sec")):
                        raise _error()
        if "summary_info" in row:
            summary = row["summary_info"]
            if not isinstance(summary, dict):
                raise _error()
            for field in ("checkin_count", "regular_work_sec", "standard_work_sec", "work_days", "regular_days", "rest_days", "except_days"):
                if field in summary and not _uint32(summary[field]):
                    raise _error()
            # earliest_time/lastest_time 没有明确单位，不解释为 Unix 时间。
        if "exception_infos" in row:
            for item in _object_array(row, "exception_infos"):
                if type(item.get("exception")) is not int or item["exception"] not in (1, 2, 3, 4, 5, 6):
                    raise _error()
                for field in ("count", "duration"):
                    if field in item and not _uint32(item[field]):
                        raise _error()
        normalize_supplements(kind, row)

    @sensitive_variables()
    def get_vacation_config(self):
        result = self._authenticated_get("oa/vacation/getcorpconf", {})
        values = []
        for row in _vacation_rows(result):
            quota = row.get("quota_attr")
            if quota is not None and not isinstance(quota, dict):
                raise _error()
            values.append({"id": row["id"], "name": _optional_quota_name(row, "name"),
                **{field: _optional_quota_number(row, field) for field in ("time_attr", "duration_type", "perday_duration")},
                "quota_type": _optional_quota_number(quota or {}, "type")})
        return values

    @sensitive_variables()
    def get_vacation_quota(self, user_id):
        if not _valid_text(user_id, 64):
            raise _invalid_request()
        result = self._authenticated_read("oa/vacation/getuservacationquota", {"userid": user_id})
        return [{"id": row["id"], "name": _optional_quota_name(row, "vacationname"),
                 **{field: _optional_quota_number(row, field) for field in
                    ("assignduration", "real_assignduration", "usedduration", "leftduration")}}
                for row in _vacation_rows(result)]

    @sensitive_variables()
    def get_rules(self):
        # https://developer.work.weixin.qq.com/document/path/93384：当前规则，不是历史版本。
        result = self._authenticated_read("checkin/getcorpcheckinoption", {})
        groups = _object_array(result, "group")
        for group in groups:
            if (
                not _uint32(group.get("groupid"), 1)
                or type(group.get("grouptype")) is not int or group["grouptype"] not in (1, 2, 3)
                or not _text(group.get("groupname"))
                or len(group["groupname"]) > 150
            ):
                raise _error()
            for field in ("checkindate", "spe_workdays", "spe_offdays", "schedulelist"):
                if field in group:
                    _object_array(group, field)
        return groups
