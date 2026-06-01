from rest_framework import serializers

from .models import BlogPost, EmailSubscriber, NavEntry


class NavEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = NavEntry
        fields = [
            'id',
            'scheme_code',
            'isin',
            'scheme_name',
            'nav',
            'repurchase_price',
            'sale_price',
            'nav_date',
        ]


class EmailSubscriberSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailSubscriber
        fields = [
            'id',
            'name',
            'email',
            'mobile_number',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'is_active', 'created_at', 'updated_at']


class NavCompanySchemeSerializer(serializers.Serializer):
    scheme_code = serializers.CharField()
    isin_div_payout_growth = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    isin_div_reinvestment = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    scheme_name = serializers.CharField()
    net_asset_value = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    raw_line = serializers.CharField()


class CompanyNavSummarySerializer(serializers.Serializer):
    company_name = serializers.CharField()
    nav_date = serializers.DateField()
    nav = NavCompanySchemeSerializer(many=True)


class ChatbotResponseSerializer(serializers.Serializer):
    session_id = serializers.CharField()
    language_detected = serializers.CharField()
    intent = serializers.CharField()
    detected_inputs = serializers.DictField(child=serializers.JSONField())
    assumptions = serializers.DictField(child=serializers.JSONField())
    answer = serializers.CharField()
    explanation_short = serializers.CharField()
    follow_up_question = serializers.CharField(allow_blank=True, required=False)
    metrics = serializers.DictField(child=serializers.JSONField())
    disclaimer = serializers.CharField(allow_null=True, required=False)
    provider_used = serializers.CharField()


class BlogPostSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlogPost
        fields = [
            'id',
            'heading',
            'small_content',
            'full_content',
            'blog_type',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ChatbotRequestSerializer(serializers.Serializer):
    message = serializers.CharField()
    session_id = serializers.CharField(required=False, allow_blank=True)
    language = serializers.CharField(required=False, allow_blank=True)
