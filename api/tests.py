from datetime import date
import json
from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.core.management import call_command
from django.test import override_settings
from django.test import TestCase

from django.utils import timezone

from .models import BlogPost, BlogRotationState, EmailSubscriber
from .views import summarize_company_nav_entries

class CompanyNavSummaryTests(TestCase):

	def test_groups_regular_schemes_by_company(self):
		entries = [
			{
				'company_name': 'Axis Mutual Fund',
				'scheme_code': '117446',
				'isin_div_payout_growth': 'INF846K01CB0',
				'isin_div_reinvestment': '-',
				'scheme_name': 'Axis Banking & PSU Debt Fund - Regular Plan - Growth option',
				'nav': '2743.7826',
				'nav_date': date(2026, 5, 8),
				'raw_line': 'regular row 1',
			},
			{
				'company_name': 'Axis Mutual Fund',
				'scheme_code': '120439',
				'isin_div_payout_growth': 'INF846K01CT2',
				'isin_div_reinvestment': '-',
				'scheme_name': 'Axis Banking & PSU Debt Fund - Regular Plan - Monthly IDCW',
				'nav': '1033.9706',
				'nav_date': date(2026, 5, 8),
				'raw_line': 'regular row 2',
			},
			{
				'company_name': 'Axis Mutual Fund',
				'scheme_code': '120438',
				'isin_div_payout_growth': 'INF846K01CR6',
				'isin_div_reinvestment': '-',
				'scheme_name': 'Axis Banking & PSU Debt Fund - Direct Plan - Growth Option',
				'nav': '2836.1289',
				'nav_date': date(2026, 5, 8),
				'raw_line': 'direct row',
			},
		]

		summary = summarize_company_nav_entries(entries)

		self.assertEqual(len(summary), 1)
		self.assertEqual(summary[0]['company_name'], 'Axis Mutual Fund')
		self.assertEqual([item['scheme_code'] for item in summary[0]['nav']], ['117446', '120439'])
		self.assertEqual(summary[0]['nav'][0]['scheme_name'], 'Axis Banking & PSU Debt Fund - Regular Plan - Growth option')
		self.assertEqual(summary[0]['nav'][0]['net_asset_value'], '2743.7826')


class SubscriberApiTests(TestCase):

	def test_creates_or_updates_subscriber(self):
		response = self.client.post(
			'/api/subscribers/',
			data=json.dumps({
				'name': '  Jane Doe  ',
				'email': 'Jane.Doe@example.com',
			}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 201)
		subscriber = EmailSubscriber.objects.get(email='jane.doe@example.com')
		self.assertEqual(subscriber.name, 'Jane Doe')

		response = self.client.post(
			'/api/subscribers/',
			data=json.dumps({
				'name': 'Jane Updated',
				'email': 'jane.doe@example.com',
			}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(EmailSubscriber.objects.count(), 1)
		subscriber.refresh_from_db()
		self.assertEqual(subscriber.name, 'Jane Updated')


class BlogApiTests(TestCase):

	def test_returns_four_featured_blogs(self):
		for index in range(1, 9):
			BlogPost.objects.create(
				heading=f'Blog {index}',
				small_content=f'Short content {index}',
				full_content=f'Full content {index}',
				blog_type='SIP',
			)

		response = self.client.get('/api/blogs/')

		self.assertEqual(response.status_code, 200)
		self.assertEqual(len(response.json()), 4)

	def test_rotates_featured_blogs_after_seven_days(self):
		for index in range(1, 9):
			BlogPost.objects.create(
				heading=f'Blog {index}',
				small_content=f'Short content {index}',
				full_content=f'Full content {index}',
				blog_type='MUTUAL FUNDS',
			)

		first_response = self.client.get('/api/blogs/')
		first_ids = [item['id'] for item in first_response.json()]

		state = BlogRotationState.objects.get(singleton_key='featured')
		state.cycle_started_at = timezone.now() - timedelta(days=8)
		state.save(update_fields=['cycle_started_at', 'updated_at'])

		second_response = self.client.get('/api/blogs/')
		second_ids = [item['id'] for item in second_response.json()]

		self.assertEqual(second_response.status_code, 200)
		self.assertEqual(len(first_ids), 4)
		self.assertEqual(len(second_ids), 4)
		self.assertEqual(set(first_ids).intersection(second_ids), set())


class DailyEmailCommandTests(TestCase):

	@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', DEFAULT_FROM_EMAIL='noreply@test.local')
	def test_sends_email_to_active_subscribers(self):
		EmailSubscriber.objects.create(name='John', email='john@example.com')

		call_command('send_daily_subscription_emails')

		self.assertEqual(len(mail.outbox), 1)
		self.assertEqual(mail.outbox[0].subject, 'Your daily Solid Wealth update')
		self.assertIn('John', mail.outbox[0].body)


class ChatbotApiTests(TestCase):

	def test_sip_chatbot_returns_projected_values(self):
		response = self.client.post(
			'/api/chatbot/',
			data=json.dumps({
				'message': 'If monthly investment is 5000, expected return is 12% and time period is 10 years, what is total value?',
			}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['intent'], 'sip')
		self.assertIn('total_value', payload['metrics'])
		self.assertEqual(payload['provider_used'], 'rule-engine')
		self.assertEqual(payload['disclaimer'], 'The data is AI generated, check it before using it')

	def test_emi_missing_inputs_returns_clarification(self):
		response = self.client.post(
			'/api/chatbot/',
			data=json.dumps({'message': 'Calculate EMI for me'}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['intent'], 'emi')
		self.assertIn('Please share loan amount', payload['answer'])

	def test_xirr_intent_returns_template_prompt(self):
		response = self.client.post(
			'/api/chatbot/',
			data=json.dumps({'message': 'Can you calculate XIRR for my portfolio?'}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['intent'], 'xirr')
		self.assertIn('2024-01-01:-100000', payload['answer'])

	def test_chatbot_preserves_session_id(self):
		response1 = self.client.post(
			'/api/chatbot/',
			data=json.dumps({'message': 'What is SIP?'}),
			content_type='application/json',
		)
		self.assertEqual(response1.status_code, 200)
		session_id = response1.json()['session_id']

		response2 = self.client.post(
			'/api/chatbot/',
			data=json.dumps({'message': 'Now calculate for 3000 monthly at 10% for 5 years', 'session_id': session_id}),
			content_type='application/json',
		)
		self.assertEqual(response2.status_code, 200)
		self.assertEqual(response2.json()['session_id'], session_id)
