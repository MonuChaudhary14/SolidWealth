from django.core.management.base import BaseCommand

from api.services import upsert_market_snapshot


class Command(BaseCommand):
    help = (
        "Fetch the latest market snapshot using yfinance and store it in MarketSnapshot"
    )

    def handle(self, *args, **options):
        snapshot, created = upsert_market_snapshot()
        action = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(f"{action} market snapshot for {snapshot.snapshot_date}")
        )
