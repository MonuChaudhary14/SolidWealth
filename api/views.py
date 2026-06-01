from django.http import JsonResponse
from django.utils import timezone
from django.db import transaction

import random
import requests
from datetime import datetime, timedelta

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema

from .models import BlogPost, BlogRotationState, NavEntry
from .serializers import (
	BlogPostSerializer,
	ChatbotRequestSerializer,
	ChatbotResponseSerializer,
	CompanyNavSummarySerializer,
	EmailSubscriberSerializer,
	NavEntrySerializer,
)
from .services import process_chatbot_message, upsert_subscriber


AMFI_URL = 'https://portal.amfiindia.com/spages/NAVAll.txt'
FEATURED_BLOG_COUNT = 4
FEATURED_BLOG_ROTATION_INTERVAL = timedelta(days=7)


def health_check(request):
	return JsonResponse({'status': 'ok'})


def try_parse_date(s):
	s = s.strip()
	for fmt in ('%d-%b-%Y', '%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d'):
		try:
			return datetime.strptime(s, fmt).date()
		except Exception:
			continue
	return None


def is_company_heading(line):
	line = line.strip()
	return bool(line) and 'mutual fund' in line.lower() and ';' not in line


def parse_nav_lines(text):
	lines = text.splitlines()
	entries = []
	current_company = None
	for line in lines:
		line = line.strip()
		if not line:
			continue
		if is_company_heading(line):
			current_company = line
			continue
		if line.lower().startswith('scheme code'):
			continue
		if ';' not in line:
			continue
		parts = [p.strip() for p in line.split(';')]
		if len(parts) < 6:
			continue
		nav_date = try_parse_date(parts[-1])
		if nav_date is None:
			continue
		scheme_code = parts[0]
		isin_div_payout = parts[1] if len(parts) > 1 else None
		isin_div_reinvestment = parts[2] if len(parts) > 2 else None
		scheme_name = parts[3] if len(parts) > 3 else ''
		nav_value = parts[4].replace(',', '') if len(parts) > 4 and parts[4] else None

		entries.append({
			'company_name': current_company or '',
			'scheme_code': scheme_code,
			'isin_div_payout_growth': isin_div_payout,
			'isin_div_reinvestment': isin_div_reinvestment,
			'scheme_name': scheme_name or '',
			'nav': nav_value,
			'nav_date': nav_date,
			'raw_line': line,
		})
	return entries


def summarize_company_nav_entries(entries):
	company_entries = {}
	for entry in entries:
		if 'regular' not in (entry.get('scheme_name') or '').lower():
			continue
		if not entry.get('nav_date'):
			continue
		company_name = entry.get('company_name') or 'Unknown'
		company_entries.setdefault(company_name, []).append(entry)

	summary = []
	for company_name in sorted(company_entries.keys()):
		items = company_entries[company_name]
		latest_date = max(item['nav_date'] for item in items)
		latest_items = [item for item in items if item.get('nav_date') == latest_date]
		latest_items.sort(key=lambda item: (
			item.get('scheme_name') or '',
			item.get('scheme_code') or '',
		))
		summary.append({
			'company_name': company_name,
			'nav_date': latest_date.isoformat(),
			'nav': [
				{
					'scheme_code': item.get('scheme_code'),
					'isin_div_payout_growth': item.get('isin_div_payout_growth'),
					'isin_div_reinvestment': item.get('isin_div_reinvestment'),
					'scheme_name': item.get('scheme_name'),
					'net_asset_value': item.get('nav'),
					'raw_line': item.get('raw_line'),
				}
				for item in latest_items
			],
		})

	return summary


def get_featured_blog_posts(now=None):
	now = now or timezone.now()
	current_blog_ids = list(BlogPost.objects.order_by('created_at', 'id').values_list('id', flat=True))
	if not current_blog_ids:
		return []

	with transaction.atomic():
		state, _ = BlogRotationState.objects.select_for_update().get_or_create(singleton_key='featured')
		ordered_blog_ids = [blog_id for blog_id in state.ordered_blog_ids if blog_id in current_blog_ids]

		if not ordered_blog_ids or state.cycle_started_at is None:
			ordered_blog_ids = current_blog_ids[:]
			random.shuffle(ordered_blog_ids)
			state.ordered_blog_ids = ordered_blog_ids
			state.cursor = 0
			state.cycle_started_at = now
			state.save(update_fields=['ordered_blog_ids', 'cursor', 'cycle_started_at', 'updated_at'])
			return ordered_blog_ids[:FEATURED_BLOG_COUNT]

		if state.cursor >= len(ordered_blog_ids):
			ordered_blog_ids = current_blog_ids[:]
			random.shuffle(ordered_blog_ids)
			state.ordered_blog_ids = ordered_blog_ids
			state.cursor = 0
			state.cycle_started_at = now
			state.save(update_fields=['ordered_blog_ids', 'cursor', 'cycle_started_at', 'updated_at'])
			return ordered_blog_ids[:FEATURED_BLOG_COUNT]

		if now - state.cycle_started_at >= FEATURED_BLOG_ROTATION_INTERVAL:
			next_cursor = state.cursor + FEATURED_BLOG_COUNT
			if next_cursor >= len(ordered_blog_ids):
				ordered_blog_ids = current_blog_ids[:]
				random.shuffle(ordered_blog_ids)
				state.ordered_blog_ids = ordered_blog_ids
				state.cursor = 0
				state.cycle_started_at = now
				state.save(update_fields=['ordered_blog_ids', 'cursor', 'cycle_started_at', 'updated_at'])
				return ordered_blog_ids[:FEATURED_BLOG_COUNT]

			state.ordered_blog_ids = ordered_blog_ids
			state.cursor = next_cursor
			state.cycle_started_at = now
			state.save(update_fields=['ordered_blog_ids', 'cursor', 'cycle_started_at', 'updated_at'])

		return ordered_blog_ids[state.cursor:state.cursor + FEATURED_BLOG_COUNT]


def fetch_nav_text():
	resp = requests.get(AMFI_URL, timeout=30)
	resp.raise_for_status()
	# AMFI file is usually in utf-8 or latin1; try utf-8 then fallback
	try:
		return resp.text
	except Exception:
		return resp.content.decode('latin-1')


def fetch_and_store_nav(force=False):
	text = fetch_nav_text()
	parsed = parse_nav_lines(text)
	# Replace the previous NAV dataset only after a successful fetch and parse.
	saved_dates = set()
	with transaction.atomic():
		NavEntry.objects.all().delete()
		for item in parsed:
			d = item.get('nav_date')
			if d is None:
				continue
			saved_dates.add(d)
			try:
				nav_val = None
				if item['nav']:
					nav_val = item['nav']
				NavEntry.objects.create(
					scheme_code=item['scheme_code'],
					isin=item.get('isin'),
					scheme_name=item.get('scheme_name') or '',
					nav=nav_val,
					repurchase_price=item.get('repurchase_price'),
					sale_price=item.get('sale_price'),
					nav_date=d,
					raw_line=item.get('raw_line') or '',
				)
			except Exception:
				continue
	return list(saved_dates)


class NavListAPIView(APIView):
	"""Return filtered NAV entries.

	Query params:
	- scheme_code: exact scheme code
	- q: search in scheme_name
	- date: YYYY-MM-DD date (optional)
	- limit: integer limit
	"""

	@extend_schema(
		parameters=[
			OpenApiParameter('scheme_code', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Exact scheme code'),
			OpenApiParameter('q', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Search text in scheme name'),
			OpenApiParameter('date', OpenApiTypes.DATE, OpenApiParameter.QUERY, description='Filter date in YYYY-MM-DD format'),
			OpenApiParameter('limit', OpenApiTypes.INT, OpenApiParameter.QUERY, description='Maximum rows to return'),
		],
		responses=NavEntrySerializer(many=True),
	)
	def get(self, request):
		scheme_code = request.GET.get('scheme_code')
		q = request.GET.get('q')
		date = request.GET.get('date')
		limit = int(request.GET.get('limit') or 100)

		if date:
			try:
				req_date = datetime.fromisoformat(date).date()
			except Exception:
				return Response({'error': 'invalid date'}, status=status.HTTP_400_BAD_REQUEST)
		else:
			req_date = timezone.now().date()

		qs = NavEntry.objects.filter(nav_date=req_date)
		if not qs.exists():
			# try to fetch and store today's data
			try:
				fetch_and_store_nav()
			except Exception:
				# fallback to live fetch and parse without storing
				try:
					txt = fetch_nav_text()
					parsed = parse_nav_lines(txt)
					# filter parsed in-memory
					filtered = [p for p in parsed if p.get('nav_date') == req_date]
					if scheme_code:
						filtered = [p for p in filtered if p.get('scheme_code') == scheme_code]
					if q:
						filtered = [p for p in filtered if q.lower() in (p.get('scheme_name') or '').lower()]
					return Response(filtered[:limit])
				except Exception:
					return Response({'error': 'could not fetch data'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
			qs = NavEntry.objects.filter(nav_date=req_date)

		if scheme_code:
			qs = qs.filter(scheme_code=scheme_code)
		if q:
			qs = qs.filter(scheme_name__icontains=q)

		qs = qs.order_by('scheme_code')[:limit]
		serializer = NavEntrySerializer(qs, many=True)
		return Response(serializer.data)


class CompanyNavSummaryAPIView(APIView):
	"""Return regular NAV rows grouped by company from the latest AMFI feed."""

	@extend_schema(
		parameters=[
			OpenApiParameter('company_name', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Filter by company name substring'),
		],
		responses=CompanyNavSummarySerializer(many=True),
	)
	def get(self, request):
		try:
			text = fetch_nav_text()
			parsed = parse_nav_lines(text)
		except Exception:
			return Response({'error': 'could not fetch data'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

		summary = summarize_company_nav_entries(parsed)
		company_name = request.GET.get('company_name')
		if company_name:
			summary = [item for item in summary if company_name.lower() in item['company_name'].lower()]

		return Response({
			'count': len(summary),
			'results': summary,
		})


class EmailSubscriberCreateAPIView(APIView):
	"""Create or reactivate a subscriber for the daily email."""

	@extend_schema(request=EmailSubscriberSerializer, responses=EmailSubscriberSerializer)
	def post(self, request):
		serializer = EmailSubscriberSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)

		subscriber, created = upsert_subscriber(
			name=serializer.validated_data['name'],
			email=serializer.validated_data['email'],
			mobile_number=serializer.validated_data.get('mobile_number'),
		)
		response_serializer = EmailSubscriberSerializer(subscriber)
		return Response(
			{
				'message': 'Subscription saved',
				'created': created,
				'subscriber': response_serializer.data,
			},
			status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
		)


class BlogPostListAPIView(ListAPIView):
	"""Return the blog section content for the website."""

	serializer_class = BlogPostSerializer

	def get(self, request, *args, **kwargs):
		featured_blog_ids = get_featured_blog_posts()
		if not featured_blog_ids:
			return Response([])

		blogs_by_id = {
			blog.id: blog
			for blog in BlogPost.objects.filter(id__in=featured_blog_ids)
		}
		ordered_blogs = [blogs_by_id[blog_id] for blog_id in featured_blog_ids if blog_id in blogs_by_id]
		serializer = self.get_serializer(ordered_blogs, many=True)
		return Response(serializer.data)


class BlogPostDetailAPIView(RetrieveAPIView):
	"""Return a single blog post."""

	queryset = BlogPost.objects.all()
	serializer_class = BlogPostSerializer


class ChatbotAPIView(APIView):
	"""Single endpoint chatbot for finance Q&A and calculator responses."""

	@extend_schema(request=ChatbotRequestSerializer, responses=ChatbotResponseSerializer)
	def post(self, request):
		serializer = ChatbotRequestSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)

		result = process_chatbot_message(
			message=serializer.validated_data['message'],
			session_id=serializer.validated_data.get('session_id') or None,
			language=serializer.validated_data.get('language') or None,
		)
		return Response(result, status=status.HTTP_200_OK)
