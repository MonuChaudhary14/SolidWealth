from django.http import JsonResponse
from django.utils import timezone
from django.db import transaction

import requests
from datetime import datetime

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import NavEntry
from .serializers import NavEntrySerializer


AMFI_URL = 'https://portal.amfiindia.com/spages/NAVAll.txt'


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


def parse_nav_lines(text):
	lines = text.splitlines()
	entries = []
	for line in lines:
		if not line.strip():
			continue
		# Skip header if present
		if line.lower().startswith('scheme code') or line.lower().startswith('schemecode'):
			continue
		parts = [p.strip() for p in line.split('|')]
		# Try to map common positions
		# Common expected: scheme_code | isin1 | isin2 | scheme_name | nav | repurchase | sale | date
		nav_date = None
		if parts:
			# attempt to detect date from last token
			nav_date = try_parse_date(parts[-1])
		scheme_code = parts[0] if len(parts) > 0 else ''
		isin = parts[1] if len(parts) > 1 else None
		# guess scheme_name and nav position
		scheme_name = None
		nav_value = None
		repurchase = None
		sale = None
		if nav_date and len(parts) >= 5:
			# assume scheme_name is somewhere before nav, pick the token at -4
			scheme_name = parts[-4] if len(parts) >= 4 else parts[2] if len(parts) > 2 else ''
			nav_value = parts[-3]
			repurchase = parts[-2] if len(parts) >= 2 else None
		else:
			# fallback: assign last known tokens
			if len(parts) >= 4:
				scheme_name = parts[2]
				nav_value = parts[3]
		# try convert nav to decimal-like string
		try:
			nav_val = None
			if nav_value:
				nav_val = nav_value.replace(',', '')
		except Exception:
			nav_val = None

		entries.append({
			'scheme_code': scheme_code,
			'isin': isin,
			'scheme_name': scheme_name or '',
			'nav': nav_val,
			'repurchase_price': repurchase,
			'sale_price': sale,
			'nav_date': nav_date,
			'raw_line': line,
		})
	return entries


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
	# group by nav_date and store entries for each date
	saved_dates = set()
	with transaction.atomic():
		for item in parsed:
			d = item.get('nav_date')
			if d is None:
				continue
			saved_dates.add(d)
			# remove existing for that scheme/date
			NavEntry.objects.filter(scheme_code=item['scheme_code'], nav_date=d).delete()
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
