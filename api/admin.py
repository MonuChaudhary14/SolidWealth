from django.contrib import admin

from .models import BlogPost, EmailSubscriber, NavEntry
from .models import BlogPost, EmailSubscriber, MarketSnapshot, NavEntry


@admin.register(NavEntry)
class NavEntryAdmin(admin.ModelAdmin):
	list_display = ('scheme_code', 'scheme_name', 'nav', 'nav_date')
	search_fields = ('scheme_code', 'scheme_name', 'isin')
	list_filter = ('nav_date',)


@admin.register(EmailSubscriber)
class EmailSubscriberAdmin(admin.ModelAdmin):
	list_display = ('name', 'email', 'is_active', 'created_at')
	search_fields = ('name', 'email')
	list_filter = ('is_active', 'created_at')


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
	list_display = ('heading', 'blog_type', 'created_at', 'updated_at')
	search_fields = ('heading', 'small_content', 'full_content', 'blog_type')
	list_filter = ('blog_type', 'created_at', 'updated_at')


@admin.register(MarketSnapshot)
class MarketSnapshotAdmin(admin.ModelAdmin):
	list_display = ('snapshot_date', 'gold_price', 'silver_price', 'crude_oil_price', 'bitcoin_price', 'nifty_50_value', 'sensex_value', 'usd_inr_rate', 'created_at')
	search_fields = ('snapshot_date',)
	list_filter = ('snapshot_date', 'created_at')
