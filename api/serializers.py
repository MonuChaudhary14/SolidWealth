from rest_framework import serializers

from .models import NavEntry


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
