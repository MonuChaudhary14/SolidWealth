from django.core.mail import send_mail
from django.utils import timezone
import logging
import os

import math
import os
import re
import uuid
from datetime import timedelta

import requests

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

# Configure optional file logging for per-recipient results. Set EMAIL_LOG_FILE in .env
logger = logging.getLogger('solidwealth.email_sender')
log_path = os.getenv('EMAIL_LOG_FILE')
if log_path and not logger.handlers:
	try:
		os.makedirs(os.path.dirname(log_path), exist_ok=True)
	except Exception:
		pass
	fh = logging.FileHandler(log_path)
	fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
	logger.addHandler(fh)
	logger.setLevel(logging.INFO)

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
			if logger:
				logger.info('SENT %s', subscriber.email)
		except Exception:
			failed_count += 1
			if logger:
				logger.exception('FAILED %s', subscriber.email)

	return {
		'total': subscribers.count(),
		'sent': sent_count,
		'failed': failed_count,
	}


FINANCIAL_DISCLAIMER = 'The data is AI generated, check it before using it'
DEFAULT_SESSION_TTL_MINUTES = int(os.getenv('CHAT_SESSION_TTL_MINUTES', '15'))
SESSION_MEMORY = {}

DEFAULT_MODELS = {
	'groq': os.getenv('GROQ_MODEL', 'llama-3.1-70b-versatile'),
	'gemini': os.getenv('GEMINI_MODEL', 'gemini-1.5-flash'),
	'openai': os.getenv('OPENAI_MODEL', 'gpt-4o-mini'),
}

CALCULATOR_INTENTS = {
	'sip': ['sip', 'systematic investment plan'],
	'step_up_sip': ['step up sip', 'step-up sip', 'stepup sip'],
	'lumpsum': ['lumpsum', 'lump sum'],
	'emi': ['emi', 'loan installment', 'equated monthly'],
	'swp': ['swp', 'systematic withdrawal'],
	'goal_based': ['goal', 'target corpus', 'goal based'],
	'retirement': ['retirement', 'retire'],
	'inflation': ['inflation', 'inflation-adjusted', 'real return'],
	'cagr': ['cagr'],
	'xirr': ['xirr'],
	'fd_vs': ['fd vs', 'fixed deposit vs', 'fd compare'],
}


def _clean_amount_token(token):
	t = (token or '').lower().strip()
	t = t.replace('rs.', '').replace('rs', '').replace('inr', '').replace('₹', '')
	t = t.replace(',', '').strip()
	multiplier = 1.0
	if 'crore' in t or 'cr' in t:
		multiplier = 10000000.0
		t = t.replace('crores', '').replace('crore', '').replace('cr', '').strip()
	elif 'lakh' in t or 'lac' in t:
		multiplier = 100000.0
		t = t.replace('lakhs', '').replace('lakh', '').replace('lac', '').strip()
	try:
		return float(t) * multiplier
	except Exception:
		return None


def _extract_first_amount(text, patterns):
	for pat in patterns:
		m = re.search(pat, text, flags=re.IGNORECASE)
		if m:
			amount = _clean_amount_token(m.group(1))
			if amount is not None:
				return amount
	return None


def _extract_percentage(text, patterns=None):
	patterns = patterns or [r'(\d+(?:\.\d+)?)\s*%']
	for pat in patterns:
		m = re.search(pat, text, flags=re.IGNORECASE)
		if m:
			try:
				return float(m.group(1))
			except Exception:
				continue
	return None


def _extract_years(text):
	m = re.search(r'(\d+(?:\.\d+)?)\s*(years?|yrs?|yr|year|साल)', text, flags=re.IGNORECASE)
	if m:
		try:
			return float(m.group(1))
		except Exception:
			return None
	return None


def _extract_months(text):
	m = re.search(r'(\d+(?:\.\d+)?)\s*(months?|mos?|month)', text, flags=re.IGNORECASE)
	if m:
		try:
			return float(m.group(1))
		except Exception:
			return None
	return None


def _extract_all_numbers(text):
	vals = []
	for token in re.findall(r'₹?\s*[\d,]+(?:\.\d+)?', text):
		v = _clean_amount_token(token)
		if v is not None:
			vals.append(v)
	return vals


def _indian_number_format(value):
	neg = value < 0
	value = abs(float(value))
	whole, dec = f'{value:.2f}'.split('.')
	if len(whole) > 3:
		last3 = whole[-3:]
		rest = whole[:-3]
		chunks = []
		while len(rest) > 2:
			chunks.insert(0, rest[-2:])
			rest = rest[:-2]
		if rest:
			chunks.insert(0, rest)
		whole = ','.join(chunks + [last3])
	formatted = f'₹{whole}.{dec}'
	return f'-{formatted}' if neg else formatted


def _detect_language(message):
	if re.search(r'[\u0900-\u097F]', message):
		return 'hindi'
	hinglish_tokens = ['hai', 'kya', 'kitna', 'sip', 'paise', 'saal', 'mahina']
	if any(tok in message.lower() for tok in hinglish_tokens):
		return 'hinglish'
	return 'english'


def _detect_intent(message):
	lower = message.lower()
	for intent, keywords in CALCULATOR_INTENTS.items():
		if any(keyword in lower for keyword in keywords):
			return intent
	financial_terms = ['investment', 'return', 'interest', 'fund', 'mutual', 'loan', 'finance']
	if any(term in lower for term in financial_terms):
		return 'finance_general'
	return 'general'


def _timing_mode(message):
	lower = message.lower()
	if any(k in lower for k in ['beginning', 'start of month', 'annuity due', 'month start']):
		return 'beginning'
	return 'end'


def _emi_mode(message):
	lower = message.lower()
	if 'flat' in lower:
		return 'flat'
	return 'reducing'


def _inflation_compounding_mode(message):
	lower = message.lower()
	if 'monthly inflation' in lower or 'monthly compounding' in lower:
		return 'monthly'
	return 'annual'


def _build_session_id():
	return uuid.uuid4().hex


def _purge_expired_sessions(now):
	expired = [sid for sid, data in SESSION_MEMORY.items() if data['expires_at'] <= now]
	for sid in expired:
		SESSION_MEMORY.pop(sid, None)


def _get_session(session_id=None):
	now = timezone.now()
	_purge_expired_sessions(now)
	if not session_id:
		session_id = _build_session_id()
	if session_id not in SESSION_MEMORY:
		SESSION_MEMORY[session_id] = {
			'history': [],
			'expires_at': now + timedelta(minutes=DEFAULT_SESSION_TTL_MINUTES),
		}
	else:
		SESSION_MEMORY[session_id]['expires_at'] = now + timedelta(minutes=DEFAULT_SESSION_TTL_MINUTES)
	return session_id, SESSION_MEMORY[session_id]


def _sip_future_value(monthly_investment, annual_rate, years, contribution_timing='end'):
	r = annual_rate / 100.0 / 12.0
	n = int(round(years * 12))
	if n <= 0:
		return 0.0
	if abs(r) < 1e-9:
		fv = monthly_investment * n
	else:
		fv = monthly_investment * (((1 + r) ** n - 1) / r)
		if contribution_timing == 'beginning':
			fv *= (1 + r)
	return fv


def _lumpsum_future_value(principal, annual_rate, years):
	r = annual_rate / 100.0
	return principal * ((1 + r) ** years)


def _emi_value(principal, annual_rate, years, emi_type='reducing'):
	n = int(round(years * 12))
	if n <= 0:
		return 0.0
	if emi_type == 'flat':
		total_interest = principal * (annual_rate / 100.0) * years
		return (principal + total_interest) / n
	r = annual_rate / 100.0 / 12.0
	if abs(r) < 1e-9:
		return principal / n
	return principal * r * ((1 + r) ** n) / (((1 + r) ** n) - 1)


def _cagr(initial_value, final_value, years):
	if initial_value <= 0 or final_value <= 0 or years <= 0:
		return None
	return (((final_value / initial_value) ** (1 / years)) - 1) * 100.0


def _inflation_adjusted_future_value(present_value, inflation_rate, years, compounding='annual'):
	if compounding == 'monthly':
		r = inflation_rate / 100.0 / 12.0
		n = int(round(years * 12))
		return present_value * ((1 + r) ** n)
	r = inflation_rate / 100.0
	return present_value * ((1 + r) ** years)


def _step_up_sip_future_value(start_monthly, annual_return_rate, years, annual_step_up_rate):
	months = int(round(years * 12))
	if months <= 0:
		return 0.0
	rm = annual_return_rate / 100.0 / 12.0
	current_sip = start_monthly
	fv = 0.0
	for month in range(1, months + 1):
		fv = (fv + current_sip) * (1 + rm)
		if month % 12 == 0:
			current_sip *= (1 + annual_step_up_rate / 100.0)
	return fv


def _swp_projection(initial_corpus, monthly_withdrawal, annual_return_rate, years):
	rm = annual_return_rate / 100.0 / 12.0
	months = int(round(years * 12))
	corpus = initial_corpus
	for _ in range(months):
		corpus = corpus * (1 + rm) - monthly_withdrawal
		if corpus <= 0:
			return 0.0
	return corpus


def _required_monthly_for_goal(target_corpus, current_savings, annual_return_rate, years):
	r = annual_return_rate / 100.0 / 12.0
	n = int(round(years * 12))
	if n <= 0:
		return None
	current_grown = current_savings * ((1 + r) ** n)
	remaining = target_corpus - current_grown
	if remaining <= 0:
		return 0.0
	if abs(r) < 1e-9:
		return remaining / n
	denom = ((1 + r) ** n - 1) / r
	if denom <= 0:
		return None
	return remaining / denom


def _retirement_projection(current_age, retirement_age, current_savings, monthly_investment, annual_return_rate):
	years = retirement_age - current_age
	if years <= 0:
		return None, 0
	grown_current = _lumpsum_future_value(current_savings, annual_return_rate, years)
	grown_sip = _sip_future_value(monthly_investment, annual_return_rate, years, contribution_timing='end')
	return grown_current + grown_sip, years


def _compute_xirr(cashflows, guess=0.1, max_iter=200, tol=1e-6):
	if len(cashflows) < 2:
		return None
	base_date = min(d for d, _ in cashflows)

	def f(rate):
		total = 0.0
		for dt, amount in cashflows:
			years = (dt - base_date).days / 365.0
			total += amount / ((1 + rate) ** years)
		return total

	def f_prime(rate):
		total = 0.0
		for dt, amount in cashflows:
			years = (dt - base_date).days / 365.0
			total += -years * amount / ((1 + rate) ** (years + 1))
		return total

	rate = guess
	for _ in range(max_iter):
		value = f(rate)
		if abs(value) < tol:
			return rate * 100.0
		derivative = f_prime(rate)
		if abs(derivative) < tol:
			break
		next_rate = rate - value / derivative
		if next_rate <= -0.9999:
			next_rate = -0.9999
		if abs(next_rate - rate) < tol:
			return next_rate * 100.0
		rate = next_rate
	return None


def _extract_calculator_inputs(message, intent):
	text = message.lower()
	numbers = _extract_all_numbers(message)
	annual_rate = _extract_percentage(text)
	years = _extract_years(text)

	inputs = {
		'annual_rate': annual_rate,
		'years': years,
		'months': _extract_months(text),
		'contribution_timing': _timing_mode(text),
		'emi_type': _emi_mode(text),
		'inflation_compounding': _inflation_compounding_mode(text),
	}

	if intent in ['sip', 'step_up_sip']:
		monthly = _extract_first_amount(message, [
			r'(?:monthly\s+investment|sip\s+amount|sip)\D*([₹\d,\.\s\w]+)',
			r'(?:invest\s+per\s+month|every\s+month)\D*([₹\d,\.\s\w]+)',
		])
		if monthly is None and numbers:
			monthly = numbers[0]
		inputs['monthly_investment'] = monthly
		if intent == 'step_up_sip':
			step_rate = _extract_percentage(text, [r'(\d+(?:\.\d+)?)\s*%\s*(?:step|increase|step up)', r'step\s*up\D*(\d+(?:\.\d+)?)'])
			if step_rate is None and len(re.findall(r'(\d+(?:\.\d+)?)\s*%', text)) >= 2:
				step_rate = float(re.findall(r'(\d+(?:\.\d+)?)\s*%', text)[1])
			inputs['step_up_rate'] = step_rate

	if intent == 'lumpsum':
		principal = _extract_first_amount(message, [r'(?:lumpsum|lump\s*sum|one\s*time\s*investment)\D*([₹\d,\.\s\w]+)'])
		if principal is None and numbers:
			principal = numbers[0]
		inputs['principal'] = principal

	if intent == 'emi':
		principal = _extract_first_amount(message, [r'(?:loan\s*amount|principal|loan)\D*([₹\d,\.\s\w]+)'])
		if principal is None and numbers:
			principal = numbers[0]
		inputs['principal'] = principal

	if intent == 'swp':
		corpus = _extract_first_amount(message, [r'(?:corpus|initial\s+corpus|starting\s+amount)\D*([₹\d,\.\s\w]+)'])
		withdrawal = _extract_first_amount(message, [r'(?:withdrawal|monthly\s+withdrawal|withdraw)\D*([₹\d,\.\s\w]+)'])
		if corpus is None and numbers:
			corpus = numbers[0]
		if withdrawal is None and len(numbers) > 1:
			withdrawal = numbers[1]
		inputs['initial_corpus'] = corpus
		inputs['monthly_withdrawal'] = withdrawal

	if intent == 'goal_based':
		target = _extract_first_amount(message, [r'(?:target\s+corpus|target|goal)\D*([₹\d,\.\s\w]+)'])
		current = _extract_first_amount(message, [r'(?:current\s+savings|existing\s+savings|current\s+amount)\D*([₹\d,\.\s\w]+)'])
		if target is None and numbers:
			target = numbers[0]
		if current is None and len(numbers) > 1:
			current = numbers[1]
		inputs['target_corpus'] = target
		inputs['current_savings'] = current if current is not None else 0.0

	if intent == 'retirement':
		ages = re.findall(r'(\d{2})\s*(?:years?\s*old|yrs?\s*old|age)', text)
		if len(ages) >= 2:
			inputs['current_age'] = float(ages[0])
			inputs['retirement_age'] = float(ages[1])
		else:
			two_digit_numbers = [n for n in numbers if 18 <= n <= 80]
			if len(two_digit_numbers) >= 2:
				inputs['current_age'] = two_digit_numbers[0]
				inputs['retirement_age'] = two_digit_numbers[1]
		inputs['current_savings'] = _extract_first_amount(message, [r'(?:current\s+savings|existing\s+corpus)\D*([₹\d,\.\s\w]+)'])
		inputs['monthly_investment'] = _extract_first_amount(message, [r'(?:monthly\s+investment|sip)\D*([₹\d,\.\s\w]+)'])

	if intent == 'inflation':
		present_value = _extract_first_amount(message, [r'(?:present\s+value|today\'?s\s+value|current\s+value|amount)\D*([₹\d,\.\s\w]+)'])
		if present_value is None and numbers:
			present_value = numbers[0]
		inputs['present_value'] = present_value

	if intent == 'cagr':
		initial = _extract_first_amount(message, [r'(?:initial\s+value|initial\s+amount|start\s+value)\D*([₹\d,\.\s\w]+)'])
		final = _extract_first_amount(message, [r'(?:final\s+value|final\s+amount|end\s+value)\D*([₹\d,\.\s\w]+)'])
		if initial is None and numbers:
			initial = numbers[0]
		if final is None and len(numbers) > 1:
			final = numbers[1]
		inputs['initial_value'] = initial
		inputs['final_value'] = final

	if intent == 'fd_vs':
		monthly = _extract_first_amount(message, [r'(?:monthly\s+investment|sip)\D*([₹\d,\.\s\w]+)'])
		if monthly is None and numbers:
			monthly = numbers[0]
		inputs['monthly_investment'] = monthly
		fd_rate = _extract_percentage(text, [r'fd\D*(\d+(?:\.\d+)?)\s*%', r'(\d+(?:\.\d+)?)\s*%\s*fd'])
		inputs['fd_rate'] = fd_rate

	return inputs


def _clarification_for_intent(intent):
	if intent == 'sip':
		return 'Please share monthly investment, expected annual return (%), time period (years), and timing (beginning/end of month).'
	if intent == 'lumpsum':
		return 'Please share lumpsum amount, expected annual return (%), and time period (years).'
	if intent == 'emi':
		return 'Please share loan amount, annual interest rate (%), tenure (years), and EMI type (reducing/flat).'
	if intent == 'xirr':
		return 'Please share cashflows with dates in this format: 2024-01-01:-100000, 2024-07-01:-20000, 2026-01-01:160000.'
	if intent == 'step_up_sip':
		return 'Please share monthly SIP, annual return (%), years, and annual step-up (%).'
	if intent == 'swp':
		return 'Please share initial corpus, monthly withdrawal, annual return (%), and years.'
	if intent == 'goal_based':
		return 'Please share target corpus, current savings, expected return (%), and target time (years).'
	if intent == 'retirement':
		return 'Please share current age, retirement age, current savings, monthly investment, and expected annual return (%).'
	if intent == 'inflation':
		return 'Please share current amount, inflation rate (%), years, and compounding preference (annual/monthly).'
	if intent == 'cagr':
		return 'Please share initial value, final value, and total years to compute CAGR.'
	if intent == 'fd_vs':
		return 'Please share monthly investment, expected SIP return (%), FD rate (%), and years for comparison.'
	return 'Please share your financial question with values and time period.'


def _build_calculator_response(intent, inputs):
	if intent == 'sip':
		required = ['monthly_investment', 'annual_rate', 'years']
		if any(inputs.get(k) is None for k in required):
			return None
		total = _sip_future_value(
			inputs['monthly_investment'],
			inputs['annual_rate'],
			inputs['years'],
			inputs.get('contribution_timing') or 'end',
		)
		invested = inputs['monthly_investment'] * int(round(inputs['years'] * 12))
		gain = total - invested
		return {
			'answer': f"Projected SIP value is {_indian_number_format(total)}.",
			'assumptions': {
				'contribution_timing': inputs.get('contribution_timing') or 'end',
			},
			'metrics': {
				'total_value': _indian_number_format(total),
				'invested_amount': _indian_number_format(invested),
				'estimated_gain': _indian_number_format(gain),
			},
		}

	if intent == 'step_up_sip':
		required = ['monthly_investment', 'annual_rate', 'years', 'step_up_rate']
		if any(inputs.get(k) is None for k in required):
			return None
		total = _step_up_sip_future_value(
			inputs['monthly_investment'],
			inputs['annual_rate'],
			inputs['years'],
			inputs['step_up_rate'],
		)
		return {
			'answer': f"Projected step-up SIP value is {_indian_number_format(total)}.",
			'assumptions': {'annual_step_up_rate': f"{inputs['step_up_rate']}%"},
			'metrics': {'total_value': _indian_number_format(total)},
		}

	if intent == 'lumpsum':
		required = ['principal', 'annual_rate', 'years']
		if any(inputs.get(k) is None for k in required):
			return None
		total = _lumpsum_future_value(inputs['principal'], inputs['annual_rate'], inputs['years'])
		gain = total - inputs['principal']
		return {
			'answer': f"Projected lumpsum value is {_indian_number_format(total)}.",
			'assumptions': {},
			'metrics': {
				'total_value': _indian_number_format(total),
				'invested_amount': _indian_number_format(inputs['principal']),
				'estimated_gain': _indian_number_format(gain),
			},
		}

	if intent == 'emi':
		required = ['principal', 'annual_rate', 'years']
		if any(inputs.get(k) is None for k in required):
			return None
		emi_type = inputs.get('emi_type') or 'reducing'
		emi = _emi_value(inputs['principal'], inputs['annual_rate'], inputs['years'], emi_type=emi_type)
		n = int(round(inputs['years'] * 12))
		total_payment = emi * n
		return {
			'answer': f"Estimated monthly EMI is {_indian_number_format(emi)}.",
			'assumptions': {'emi_type': emi_type},
			'metrics': {
				'monthly_emi': _indian_number_format(emi),
				'total_payment': _indian_number_format(total_payment),
			},
		}

	if intent == 'swp':
		required = ['initial_corpus', 'monthly_withdrawal', 'annual_rate', 'years']
		if any(inputs.get(k) is None for k in required):
			return None
		remaining = _swp_projection(
			inputs['initial_corpus'],
			inputs['monthly_withdrawal'],
			inputs['annual_rate'],
			inputs['years'],
		)
		return {
			'answer': f"Estimated corpus after SWP period is {_indian_number_format(remaining)}.",
			'assumptions': {},
			'metrics': {'remaining_corpus': _indian_number_format(remaining)},
		}

	if intent == 'goal_based':
		required = ['target_corpus', 'current_savings', 'annual_rate', 'years']
		if any(inputs.get(k) is None for k in required):
			return None
		required_monthly = _required_monthly_for_goal(
			inputs['target_corpus'],
			inputs['current_savings'],
			inputs['annual_rate'],
			inputs['years'],
		)
		if required_monthly is None:
			return None
		return {
			'answer': f"Required monthly investment for your goal is {_indian_number_format(required_monthly)}.",
			'assumptions': {},
			'metrics': {'required_monthly_investment': _indian_number_format(required_monthly)},
		}

	if intent == 'retirement':
		required = ['current_age', 'retirement_age', 'current_savings', 'monthly_investment', 'annual_rate']
		if any(inputs.get(k) is None for k in required):
			return None
		corpus, years = _retirement_projection(
			inputs['current_age'],
			inputs['retirement_age'],
			inputs['current_savings'],
			inputs['monthly_investment'],
			inputs['annual_rate'],
		)
		if corpus is None:
			return None
		return {
			'answer': f"Projected retirement corpus in {int(years)} years is {_indian_number_format(corpus)}.",
			'assumptions': {},
			'metrics': {'retirement_corpus': _indian_number_format(corpus)},
		}

	if intent == 'inflation':
		required = ['present_value', 'annual_rate', 'years']
		if any(inputs.get(k) is None for k in required):
			return None
		fv = _inflation_adjusted_future_value(
			inputs['present_value'],
			inputs['annual_rate'],
			inputs['years'],
			inputs.get('inflation_compounding') or 'annual',
		)
		return {
			'answer': f"Inflation-adjusted future value is {_indian_number_format(fv)}.",
			'assumptions': {'compounding': inputs.get('inflation_compounding') or 'annual'},
			'metrics': {'future_value': _indian_number_format(fv)},
		}

	if intent == 'cagr':
		required = ['initial_value', 'final_value', 'years']
		if any(inputs.get(k) is None for k in required):
			return None
		value = _cagr(inputs['initial_value'], inputs['final_value'], inputs['years'])
		if value is None:
			return None
		return {
			'answer': f"CAGR is {value:.2f}%.",
			'assumptions': {},
			'metrics': {'cagr': f'{value:.2f}%'},
		}

	if intent == 'fd_vs':
		required = ['monthly_investment', 'annual_rate', 'fd_rate', 'years']
		if any(inputs.get(k) is None for k in required):
			return None
		sip_value = _sip_future_value(inputs['monthly_investment'], inputs['annual_rate'], inputs['years'])
		fd_value = _sip_future_value(inputs['monthly_investment'], inputs['fd_rate'], inputs['years'])
		recommendation = 'SIP projected value is higher.' if sip_value > fd_value else 'FD projected value is higher.'
		return {
			'answer': recommendation,
			'assumptions': {},
			'metrics': {
				'sip_projected_value': _indian_number_format(sip_value),
				'fd_projected_value': _indian_number_format(fd_value),
			},
		}

	if intent == 'xirr':
		return None

	return None


def _build_system_prompt(language):
	lang = {
		'english': 'English',
		'hindi': 'Hindi',
		'hinglish': 'Hinglish',
	}.get(language, 'English')
	return (
		'You are a financial assistant with advisor tone. '
		'Be concise and practical, avoid guarantees, and do not provide unsafe promises. '
		f'Respond in {lang}. '
		'If the user asks for recommendations, explain assumptions briefly and ask one relevant follow-up question.'
	)


def _call_openai_like(api_url, api_key, model, messages):
	resp = requests.post(
		api_url,
		headers={
			'Authorization': f'Bearer {api_key}',
			'Content-Type': 'application/json',
		},
		json={
			'model': model,
			'messages': messages,
			'temperature': 0.2,
		},
		timeout=20,
	)
	resp.raise_for_status()
	data = resp.json()
	return data['choices'][0]['message']['content']


def _call_gemini(api_key, model, messages):
	url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}'
	joined = '\n'.join([f"{m['role']}: {m['content']}" for m in messages])
	payload = {
		'contents': [
			{
				'parts': [{'text': joined}],
			}
		],
		'generationConfig': {'temperature': 0.2},
	}
	resp = requests.post(url, json=payload, timeout=20)
	resp.raise_for_status()
	data = resp.json()
	return data['candidates'][0]['content']['parts'][0]['text']


def _llm_fallback_answer(message, language, history):
	system_prompt = _build_system_prompt(language)
	messages = [{'role': 'system', 'content': system_prompt}]
	for item in history[-10:]:
		messages.append({'role': item['role'], 'content': item['content']})
	messages.append({'role': 'user', 'content': message})

	providers = [
		('groq', os.getenv('GROQ_API_KEY')),
		('gemini', os.getenv('GEMINI_API_KEY')),
		('openai', os.getenv('OPENAI_API_KEY')),
	]

	for name, key in providers:
		if not key:
			continue
		try:
			if name == 'groq':
				answer = _call_openai_like(
					'https://api.groq.com/openai/v1/chat/completions',
					key,
					DEFAULT_MODELS['groq'],
					messages,
				)
				return answer, 'groq'
			if name == 'gemini':
				answer = _call_gemini(key, DEFAULT_MODELS['gemini'], messages)
				return answer, 'gemini'
			if name == 'openai':
				answer = _call_openai_like(
					'https://api.openai.com/v1/chat/completions',
					key,
					DEFAULT_MODELS['openai'],
					messages,
				)
				return answer, 'openai'
		except Exception:
			continue

	return (
		'I can help with SIP, Lumpsum, EMI, SWP, Goal, Retirement, Inflation, CAGR, XIRR, and FD comparisons. '
		'Please share exact values (amount, return rate, time period) so I can calculate accurately.',
		'none',
	)


def process_chatbot_message(message, session_id=None, language=None):
	session_id, session = _get_session(session_id=session_id)
	msg = (message or '').strip()
	lang = language or _detect_language(msg)
	intent = _detect_intent(msg)

	inputs = _extract_calculator_inputs(msg, intent)
	calculator_response = _build_calculator_response(intent, inputs)
	disclaimer = FINANCIAL_DISCLAIMER if intent != 'general' else None
	provider_used = 'rule-engine'

	if intent == 'xirr':
		answer = _clarification_for_intent('xirr')
		explanation_short = 'XIRR needs date-wise cashflows with positive and negative values.'
		assumptions = {}
		metrics = {}
		follow_up = 'Would you like me to provide a sample XIRR input template with your actual numbers?'
	elif calculator_response is None and intent in CALCULATOR_INTENTS:
		answer = _clarification_for_intent(intent)
		explanation_short = 'I need a few mandatory inputs to calculate this accurately.'
		assumptions = {}
		metrics = {}
		follow_up = 'Share the missing values and I will compute instantly.'
	elif calculator_response is not None:
		answer = calculator_response['answer']
		explanation_short = 'This estimate is based on the inputs detected from your message.'
		assumptions = calculator_response.get('assumptions') or {}
		metrics = calculator_response.get('metrics') or {}
		follow_up = 'Do you want a sensitivity check with ±1% return rate?'
	else:
		answer, provider_used = _llm_fallback_answer(msg, lang, session['history'])
		explanation_short = 'Answer generated with advisor-style guidance and your recent session context.'
		assumptions = {}
		metrics = {}
		follow_up = 'Would you like me to convert this into a calculator-ready example with numbers?'

	session['history'].append({'role': 'user', 'content': msg})
	session['history'].append({'role': 'assistant', 'content': answer})

	return {
		'session_id': session_id,
		'language_detected': lang,
		'intent': intent,
		'detected_inputs': {k: v for k, v in inputs.items() if v is not None},
		'assumptions': assumptions,
		'answer': answer,
		'explanation_short': explanation_short,
		'follow_up_question': follow_up,
		'metrics': metrics,
		'disclaimer': disclaimer,
		'provider_used': provider_used,
	}