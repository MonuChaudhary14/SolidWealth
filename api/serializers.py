import re

from rest_framework import serializers

from .models import (
    BlogPost,
    EmailSubscriber,
    MarketSnapshot,
    MutualFundPerformance,
    NavEntry,
)


def validate_mobile_number(value):
    if value in (None, ""):
        return value
    v = re.sub(r"\s+", " ", value).strip()
    if len(v) > 20:
        raise serializers.ValidationError("Mobile number too long")

    if not re.match(r"^\+?\d{1,3}\s?\d[\d\s]{4,}$", v):
        raise serializers.ValidationError("Invalid mobile number format")
    return v


class NavEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = NavEntry
        fields = [
            "id",
            "company_name",
            "scheme_code",
            "isin",
            "scheme_name",
            "nav",
            "repurchase_price",
            "sale_price",
            "nav_date",
        ]


class EmailSubscriberSerializer(serializers.ModelSerializer):
    mobile_number = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=20,
        validators=[validate_mobile_number],
    )
    source = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=100,
    )
    interests = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        default=list,
    )

    class Meta:
        model = EmailSubscriber
        fields = [
            "id",
            "name",
            "email",
            "mobile_number",
            "source",
            "interests",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_active", "created_at", "updated_at"]


class NavCompanySchemeSerializer(serializers.Serializer):
    scheme_code = serializers.CharField()
    isin_div_payout_growth = serializers.CharField(
        allow_blank=True, allow_null=True, required=False
    )
    isin_div_reinvestment = serializers.CharField(
        allow_blank=True, allow_null=True, required=False
    )
    scheme_name = serializers.CharField()
    net_asset_value = serializers.CharField(
        allow_blank=True, allow_null=True, required=False
    )
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
            "id",
            "heading",
            "small_content",
            "full_content",
            "blog_type",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class MarketSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketSnapshot
        fields = [
            "id",
            "snapshot_date",
            "gold_price",
            "silver_price",
            "crude_oil_price",
            "bitcoin_price",
            "nifty_50_value",
            "sensex_value",
            "usd_inr_rate",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class ChatbotRequestSerializer(serializers.Serializer):
    message = serializers.CharField()
    session_id = serializers.CharField(required=False, allow_blank=True)
    language = serializers.CharField(required=False, allow_blank=True)


class MutualFundPerformanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = MutualFundPerformance
        fields = "__all__"


class MutualFundCategorySerializer(serializers.Serializer):
    category = serializers.CharField()
    periods = serializers.ListField(child=serializers.CharField(), required=False, default=list)


class MarketIndexItemSerializer(serializers.Serializer):
    symbol = serializers.CharField()
    name = serializers.CharField()
    category = serializers.CharField(default="indices")
    value = serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True)
    unit = serializers.CharField(default="points")
    formatted = serializers.CharField()


class MarketMetalItemSerializer(serializers.Serializer):
    symbol = serializers.CharField()
    name = serializers.CharField()
    category = serializers.CharField(default="metals")
    currency = serializers.CharField(default="INR")
    price_per_gram_inr = serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True)
    price_per_10g_inr = serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True, required=False)
    price_per_kg_inr = serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True, required=False)
    price_per_gram_usd = serializers.DecimalField(max_digits=20, decimal_places=4, allow_null=True)
    formatted = serializers.CharField()


class MarketMacroItemSerializer(serializers.Serializer):
    symbol = serializers.CharField()
    name = serializers.CharField()
    category = serializers.CharField(default="macro")
    currency = serializers.CharField(default="INR")
    value_inr = serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True)
    value_usd = serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True, required=False)
    formatted = serializers.CharField()


class MarketCryptoItemSerializer(serializers.Serializer):
    symbol = serializers.CharField()
    name = serializers.CharField()
    category = serializers.CharField(default="crypto")
    currency = serializers.CharField(default="INR")
    price_in_inr = serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True)
    price_in_usd = serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True)
    formatted = serializers.CharField()


class MarketSummarySerializer(serializers.Serializer):
    snapshot_date = serializers.DateField()
    currency = serializers.CharField(default="INR")
    usd_inr_rate = serializers.DecimalField(max_digits=10, decimal_places=4, allow_null=True)
    indices = serializers.DictField()
    metals = serializers.DictField()
    macro = serializers.DictField()
    crypto = serializers.DictField()

