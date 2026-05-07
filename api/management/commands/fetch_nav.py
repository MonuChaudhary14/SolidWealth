from django.core.management.base import BaseCommand

from api.views import fetch_and_store_nav


class Command(BaseCommand):
    help = 'Fetch NAVAll.txt from AMFI and store into NavEntry model'

    def handle(self, *args, **options):
        dates = fetch_and_store_nav(force=True)
        if dates:
            self.stdout.write(self.style.SUCCESS(f'Saved NAV data for dates: {dates}'))
        else:
            self.stdout.write(self.style.WARNING('No NAV data found or saved.'))
