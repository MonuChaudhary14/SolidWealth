from rest_framework import serializers

from .models import EmailSubscriber, NavEntry


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
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'is_active', 'created_at', 'updated_at']
