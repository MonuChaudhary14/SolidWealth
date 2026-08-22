from django.core.management.base import BaseCommand

from api.services import send_daily_subscription_emails
from api.tasks import send_daily_subscription_emails_task


class Command(BaseCommand):
    help = "Send the daily email to all active subscribers."

    def add_arguments(self, parser):
        parser.add_argument(
            "--async",
            action="store_true",
            dest="run_async",
            help="Queue with Celery instead of sending immediately.",
        )

    def handle(self, *args, **options):
        if options.get("run_async"):
            async_result = send_daily_subscription_emails_task.delay()
            self.stdout.write(
                self.style.SUCCESS(f"Queued daily email task: {async_result.id}")
            )
            return

        result = send_daily_subscription_emails()
        self.stdout.write(
            self.style.SUCCESS(
                "Email run complete. "
                f"Total: {result['total']}, Sent: {result['sent']}, Failed: {result['failed']}"
            )
        )
