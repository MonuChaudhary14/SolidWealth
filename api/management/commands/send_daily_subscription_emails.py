from django.core.management.base import BaseCommand

from api.tasks import send_daily_subscription_emails_task


class Command(BaseCommand):
	help = 'Queue the daily email job for all active subscribers.'

	def handle(self, *args, **options):
		async_result = send_daily_subscription_emails_task.delay()
		self.stdout.write(self.style.SUCCESS(f'Queued daily email task: {async_result.id}'))