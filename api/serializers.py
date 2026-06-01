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
