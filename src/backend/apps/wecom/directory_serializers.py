from rest_framework import serializers


class StrictSerializer(serializers.Serializer):
    def validate(self, attrs):
        if set(self.initial_data) - set(self.fields):
            raise serializers.ValidationError("请求包含不支持的字段。")
        return attrs


class SubmissionSerializer(StrictSerializer):
    preview_token = serializers.CharField(max_length=500000, trim_whitespace=False)
    apply_departments = serializers.BooleanField(default=False)


class DirectoryPreviewQuerySerializer(StrictSerializer):
    apply_departments = serializers.BooleanField(default=False)


def user_id_field():
    return serializers.RegexField(r"^[A-Za-z0-9_.@-]{1,64}$", trim_whitespace=False)


class DirectorySyncSerializer(SubmissionSerializer):
    user_ids = serializers.ListField(child=user_id_field(), allow_empty=False, max_length=500)
    confirmed_new_user_ids = serializers.ListField(child=user_id_field(), default=list, max_length=500)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        selected = {value.lower() for value in attrs["user_ids"]}
        confirmed = {value.lower() for value in attrs["confirmed_new_user_ids"]}
        if len(selected) != len(attrs["user_ids"]) or len(confirmed) != len(attrs["confirmed_new_user_ids"]):
            raise serializers.ValidationError("同一成员不能重复提交，UserID 不区分大小写。")
        if not confirmed.issubset(selected):
            raise serializers.ValidationError("人工确认新建的成员必须包含在本次选择中。")
        return attrs


class DirectoryMatchSerializer(SubmissionSerializer):
    user_id = user_id_field()
    employee_id = serializers.UUIDField()
    employee_etag = serializers.CharField(max_length=100, trim_whitespace=False)
    confirmed = serializers.BooleanField()

    def validate_confirmed(self, value):
        if not value:
            raise serializers.ValidationError("必须确认成员与所选员工为同一人。")
        return value


class DirectoryEmployeeSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    employee_code = serializers.CharField()
    display_name = serializers.CharField()
    status = serializers.ChoiceField(choices=["ACTIVE", "INACTIVE", "LEFT"])
    archived = serializers.BooleanField()
    has_account = serializers.BooleanField()
    account_active = serializers.BooleanField()
    etag = serializers.CharField()


class DirectoryDepartmentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    parentid = serializers.IntegerField()
    name = serializers.CharField()


class DepartmentAssignmentSerializer(serializers.Serializer):
    department_id = serializers.UUIDField()
    department_name = serializers.CharField()
    is_primary = serializers.BooleanField()


class DepartmentPlanSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["READY", "PENDING", "PRESERVED"])
    reason = serializers.CharField()
    assignments = DepartmentAssignmentSerializer(many=True)


class DirectoryMemberSerializer(serializers.Serializer):
    userid = serializers.CharField()
    name = serializers.CharField(allow_blank=True)
    department = serializers.ListField(child=serializers.IntegerField())
    main_department = serializers.IntegerField(allow_null=True)
    status = serializers.IntegerField(allow_null=True)
    status_label = serializers.CharField()
    action = serializers.ChoiceField(choices=["CREATE", "EXISTING", "REVIEW", "SKIP"])
    reason = serializers.CharField()
    employee = DirectoryEmployeeSerializer(allow_null=True)
    candidates = DirectoryEmployeeSerializer(many=True)
    department_plan = DepartmentPlanSerializer(required=False)


class DirectoryPreviewSerializer(serializers.Serializer):
    corp_id = serializers.CharField()
    departments = DirectoryDepartmentSerializer(many=True)
    members = DirectoryMemberSerializer(many=True)
    preview_token = serializers.CharField()
    apply_departments = serializers.BooleanField()


class DirectoryPreviewResponseSerializer(serializers.Serializer):
    data = DirectoryPreviewSerializer()


class DirectoryResultSerializer(serializers.Serializer):
    user_id = serializers.CharField()
    employee_id = serializers.UUIDField()
    result = serializers.ChoiceField(choices=["CREATED", "MATCHED", "EXISTING"])
    department_status = serializers.ChoiceField(choices=["APPLIED", "PENDING", "PRESERVED"], required=False)
    department_reason = serializers.CharField(required=False)


class DirectorySyncResponseSerializer(serializers.Serializer):
    data = DirectoryResultSerializer(many=True)


class DirectoryMatchResponseSerializer(serializers.Serializer):
    data = DirectoryResultSerializer()
