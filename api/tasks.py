from celery import shared_task

from .services import send_daily_subscription_emails


@shared_task(bind=True, name='api.send_daily_subscription_emails_task')
def send_daily_subscription_emails_task(self):
	return send_daily_subscription_emails()