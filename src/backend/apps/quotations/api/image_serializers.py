from rest_framework import serializers


class QuotationInquiryImageSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    url = serializers.CharField()


class QuotationProductImageInputSerializer(serializers.Serializer):
    file = serializers.FileField(required=False, help_text='上传新产品图片，与 source_image_id 二选一。')
    source_image_id = serializers.UUIDField(required=False, help_text='选用该报价来源询盘的图片，与 file 二选一。')
