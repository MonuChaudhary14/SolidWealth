from django.contrib import admin

from .models import EmailSubscriber, NavEntry


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
