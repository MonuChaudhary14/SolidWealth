from django.core.mail import send_mail

from .models import EmailSubscriber


DAILY_EMAIL_SUBJECT = 'Your daily Solid Wealth update'
DAILY_EMAIL_BODY = (
	"Hello {name},\n\n"
	"This is your automated daily Solid Wealth email. We will replace this placeholder "
	"with the final content you share later.\n\n"
	"Regards,\n"
	"Solid Wealth Team"
)


def upsert_subscriber(name, email):
	subscriber, created = EmailSubscriber.objects.update_or_create(
		email=(email or '').strip().lower(),
		defaults={
			'name': (name or '').strip(),
			'is_active': True,
		},
	)
	return subscriber, created


def build_daily_email_body(subscriber):
	return DAILY_EMAIL_BODY.format(name=subscriber.name or 'there')


def send_daily_subscription_emails():
	subscribers = EmailSubscriber.objects.filter(is_active=True).order_by('name', 'email')
	sent_count = 0
	failed_count = 0

	for subscriber in subscribers:
		try:
			send_mail(
				subject=DAILY_EMAIL_SUBJECT,
				message=build_daily_email_body(subscriber),
				from_email=None,
				recipient_list=[subscriber.email],
				fail_silently=False,
			)
			sent_count += 1
		except Exception:
			failed_count += 1

	return {
		'total': subscribers.count(),
		'sent': sent_count,
		'failed': failed_count,
	}