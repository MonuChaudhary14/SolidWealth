import random
from datetime import datetime, timedelta

import requests
from django.core.cache import cache
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    BlogPost,
    BlogRotationState,
    MarketSnapshot,
    MutualFundPerformance,
    NavEntry,
)
from .serializers import (
    BlogPostSerializer,
    ChatbotRequestSerializer,
    ChatbotResponseSerializer,
    CompanyNavSummarySerializer,
    EmailSubscriberSerializer,
    MarketSnapshotSerializer,
    MarketSummarySerializer,
    MutualFundCategorySerializer,
    MutualFundPerformanceSerializer,
    NavEntrySerializer,
)
from .services import process_chatbot_message, upsert_subscriber

AMFI_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"
FEATURED_BLOG_COUNT = 4
FEATURED_BLOG_ROTATION_INTERVAL = timedelta(days=7)


def health_check(request):
    return JsonResponse({"status": "ok"})


def try_parse_date(s):
    s = s.strip()
    for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None


def is_company_heading(line):
    line = line.strip()
    return bool(line) and "mutual fund" in line.lower() and ";" not in line


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
        if line.lower().startswith("scheme code"):
            continue
        if ";" not in line:
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 6:
            continue
        nav_date = try_parse_date(parts[-1])
        if nav_date is None:
            continue
        scheme_code = parts[0]
        isin_div_payout = parts[1] if len(parts) > 1 and parts[1] != "-" else None
        isin_div_reinvestment = parts[2] if len(parts) > 2 and parts[2] != "-" else None

        if len(parts) >= 8:
            base_scheme_name = parts[3]
            plan = parts[4]
            option = parts[5]
            components = [base_scheme_name]
            if plan:
                components.append(plan)
            if option:
                components.append(option)
            scheme_name = " - ".join(components)
            raw_nav = (
                parts[6].replace(",", "")
                if len(parts) > 6 and parts[6] and parts[6] != "-"
                else None
            )
        else:
            scheme_name = parts[3] if len(parts) > 3 else ""
            raw_nav = (
                parts[4].replace(",", "")
                if len(parts) > 4 and parts[4] and parts[4] != "-"
                else None
            )

        try:
            if raw_nav is not None:
                float(raw_nav)
                nav_value = raw_nav
            else:
                nav_value = None
        except ValueError:
            nav_value = None

        entries.append(
            {
                "company_name": current_company or "",
                "scheme_code": scheme_code,
                "isin": isin_div_payout or isin_div_reinvestment,
                "isin_div_payout_growth": isin_div_payout,
                "isin_div_reinvestment": isin_div_reinvestment,
                "scheme_name": scheme_name or "",
                "nav": nav_value,
                "nav_date": nav_date,
                "raw_line": line,
            }
        )
    return entries


def summarize_company_nav_entries(entries):
    company_entries = {}
    for entry in entries:
        if "regular" not in (entry.get("scheme_name") or "").lower():
            continue
        if not entry.get("nav_date"):
            continue
        company_name = entry.get("company_name") or "Unknown"
        company_entries.setdefault(company_name, []).append(entry)

    summary = []
    for company_name in sorted(company_entries.keys()):
        items = company_entries[company_name]
        latest_date = max(item["nav_date"] for item in items)
        latest_items = [item for item in items if item.get("nav_date") == latest_date]
        latest_items.sort(
            key=lambda item: (
                item.get("scheme_name") or "",
                item.get("scheme_code") or "",
            )
        )
        summary.append(
            {
                "company_name": company_name,
                "nav_date": latest_date.isoformat(),
                "nav": [
                    {
                        "scheme_code": item.get("scheme_code"),
                        "isin_div_payout_growth": item.get("isin_div_payout_growth"),
                        "isin_div_reinvestment": item.get("isin_div_reinvestment"),
                        "scheme_name": item.get("scheme_name"),
                        "net_asset_value": item.get("nav"),
                        "raw_line": item.get("raw_line"),
                    }
                    for item in latest_items
                ],
            }
        )

    return summary


def get_featured_blog_posts(now=None):
    now = now or timezone.now()
    current_blog_ids = list(
        BlogPost.objects.order_by("created_at", "id").values_list("id", flat=True)
    )
    if not current_blog_ids:
        return []

    with transaction.atomic():
        state, _ = BlogRotationState.objects.select_for_update().get_or_create(
            singleton_key="featured"
        )
        ordered_blog_ids = [
            blog_id for blog_id in state.ordered_blog_ids if blog_id in current_blog_ids
        ]

        if not ordered_blog_ids or state.cycle_started_at is None:
            ordered_blog_ids = current_blog_ids[:]
            random.shuffle(ordered_blog_ids)
            state.ordered_blog_ids = ordered_blog_ids
            state.cursor = 0
            state.cycle_started_at = now
            state.save(
                update_fields=[
                    "ordered_blog_ids",
                    "cursor",
                    "cycle_started_at",
                    "updated_at",
                ]
            )
            return ordered_blog_ids[:FEATURED_BLOG_COUNT]

        if state.cursor >= len(ordered_blog_ids):
            ordered_blog_ids = current_blog_ids[:]
            random.shuffle(ordered_blog_ids)
            state.ordered_blog_ids = ordered_blog_ids
            state.cursor = 0
            state.cycle_started_at = now
            state.save(
                update_fields=[
                    "ordered_blog_ids",
                    "cursor",
                    "cycle_started_at",
                    "updated_at",
                ]
            )
            return ordered_blog_ids[:FEATURED_BLOG_COUNT]

        if now - state.cycle_started_at >= FEATURED_BLOG_ROTATION_INTERVAL:
            next_cursor = state.cursor + FEATURED_BLOG_COUNT
            if next_cursor >= len(ordered_blog_ids):
                ordered_blog_ids = current_blog_ids[:]
                random.shuffle(ordered_blog_ids)
                state.ordered_blog_ids = ordered_blog_ids
                state.cursor = 0
                state.cycle_started_at = now
                state.save(
                    update_fields=[
                        "ordered_blog_ids",
                        "cursor",
                        "cycle_started_at",
                        "updated_at",
                    ]
                )
                return ordered_blog_ids[:FEATURED_BLOG_COUNT]

            state.ordered_blog_ids = ordered_blog_ids
            state.cursor = next_cursor
            state.cycle_started_at = now
            state.save(
                update_fields=[
                    "ordered_blog_ids",
                    "cursor",
                    "cycle_started_at",
                    "updated_at",
                ]
            )

        return ordered_blog_ids[state.cursor : state.cursor + FEATURED_BLOG_COUNT]


def fetch_nav_text():
    resp = requests.get(AMFI_URL, timeout=30)
    resp.raise_for_status()

    try:
        return resp.text
    except Exception:
        return resp.content.decode("latin-1")


def fetch_and_store_nav(force=False):
    text = fetch_nav_text()
    parsed = parse_nav_lines(text)

    saved_dates = set()
    entries_to_create = []
    for item in parsed:
        d = item.get("nav_date")
        if d is None:
            continue
        saved_dates.add(d)
        nav_val = item.get("nav")
        entries_to_create.append(
            NavEntry(
                company_name=item.get("company_name") or "",
                scheme_code=item["scheme_code"],
                isin=item.get("isin"),
                isin_div_payout_growth=item.get("isin_div_payout_growth"),
                isin_div_reinvestment=item.get("isin_div_reinvestment"),
                scheme_name=item.get("scheme_name") or "",
                nav=nav_val,
                repurchase_price=item.get("repurchase_price"),
                sale_price=item.get("sale_price"),
                nav_date=d,
                raw_line=item.get("raw_line") or "",
            )
        )

    with transaction.atomic():
        NavEntry.objects.all().delete()
        NavEntry.objects.bulk_create(entries_to_create, batch_size=2000)

    try:
        summary = summarize_company_nav_entries(parsed)
        cache.set("company_nav_summary_cache", summary, timeout=86400)
    except Exception:
        pass

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
            OpenApiParameter(
                "scheme_code",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description="Exact scheme code",
            ),
            OpenApiParameter(
                "q",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description="Search text in scheme name",
            ),
            OpenApiParameter(
                "date",
                OpenApiTypes.DATE,
                OpenApiParameter.QUERY,
                description="Filter date in YYYY-MM-DD format",
            ),
            OpenApiParameter(
                "limit",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                description="Maximum rows to return",
            ),
        ],
        responses=NavEntrySerializer(many=True),
    )
    def get(self, request):
        scheme_code = request.GET.get("scheme_code")
        q = request.GET.get("q")
        date = request.GET.get("date")
        limit = int(request.GET.get("limit") or 100)

        if date:
            try:
                req_date = datetime.fromisoformat(date).date()
            except Exception:
                return Response(
                    {"error": "invalid date"}, status=status.HTTP_400_BAD_REQUEST
                )
        else:
            req_date = timezone.now().date()

        qs = NavEntry.objects.filter(nav_date=req_date)
        if not qs.exists():
            try:
                fetch_and_store_nav()
            except Exception:
                try:
                    txt = fetch_nav_text()
                    parsed = parse_nav_lines(txt)

                    filtered = [p for p in parsed if p.get("nav_date") == req_date]
                    if scheme_code:
                        filtered = [
                            p for p in filtered if p.get("scheme_code") == scheme_code
                        ]
                    if q:
                        filtered = [
                            p
                            for p in filtered
                            if q.lower() in (p.get("scheme_name") or "").lower()
                        ]
                    return Response(filtered[:limit])
                except Exception:
                    return Response(
                        {"error": "could not fetch data"},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE,
                    )
            qs = NavEntry.objects.filter(nav_date=req_date)

        if scheme_code:
            qs = qs.filter(scheme_code=scheme_code)
        if q:
            qs = qs.filter(scheme_name__icontains=q)

        qs = qs.order_by("scheme_code")[:limit]
        serializer = NavEntrySerializer(qs, many=True)
        return Response(serializer.data)


def get_company_nav_summary():
    summary = cache.get("company_nav_summary_cache")
    if summary is not None:
        return summary

    db_entries = NavEntry.objects.filter(scheme_name__icontains="regular")
    if db_entries.exists():
        entries = list(
            db_entries.values(
                "company_name",
                "scheme_code",
                "isin_div_payout_growth",
                "isin_div_reinvestment",
                "scheme_name",
                "nav",
                "nav_date",
                "raw_line",
            )
        )
        summary = summarize_company_nav_entries(entries)
        cache.set("company_nav_summary_cache", summary, timeout=86400)
        return summary

    fetch_and_store_nav()
    summary = cache.get("company_nav_summary_cache")
    if summary is not None:
        return summary

    text = fetch_nav_text()
    parsed = parse_nav_lines(text)
    summary = summarize_company_nav_entries(parsed)
    cache.set("company_nav_summary_cache", summary, timeout=86400)
    return summary


class CompanyNavSummaryAPIView(APIView):
    """Return regular NAV rows grouped by company from the latest AMFI feed."""

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "company_name",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description="Filter by company name substring",
            ),
        ],
        responses=CompanyNavSummarySerializer(many=True),
    )
    def get(self, request):
        try:
            summary = get_company_nav_summary()
        except Exception:
            return Response(
                {"error": "could not fetch data"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        company_name = request.GET.get("company_name")
        if company_name:
            summary = [
                item
                for item in summary
                if company_name.lower() in item["company_name"].lower()
            ]

        return Response(
            {
                "count": len(summary),
                "results": summary,
            }
        )


class MarketSnapshotAPIView(APIView):
    """Return the latest stored market snapshot or create one when missing."""

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "date",
                OpenApiTypes.DATE,
                OpenApiParameter.QUERY,
                description="Snapshot date in YYYY-MM-DD format",
            ),
        ],
        responses=MarketSnapshotSerializer,
    )
    def get(self, request):
        date_value = request.GET.get("date")
        if date_value:
            try:
                snapshot_date = datetime.fromisoformat(date_value).date()
            except Exception:
                return Response(
                    {"error": "invalid date"}, status=status.HTTP_400_BAD_REQUEST
                )
            snapshot = MarketSnapshot.objects.filter(
                snapshot_date=snapshot_date
            ).first()
            if snapshot is None:
                return Response(
                    {"error": "snapshot not found"}, status=status.HTTP_404_NOT_FOUND
                )
            return Response(MarketSnapshotSerializer(snapshot).data)

        snapshot = MarketSnapshot.objects.order_by(
            "-snapshot_date", "-created_at"
        ).first()
        if snapshot is None:
            return Response(
                {"error": "snapshot not available"}, status=status.HTTP_404_NOT_FOUND
            )

        return Response(MarketSnapshotSerializer(snapshot).data)


def _format_inr(val, decimals=2):
    if val is None:
        return "-"
    try:
        val_float = float(val)
        return f"₹{val_float:,.{decimals}f}"
    except Exception:
        return f"₹{val}"


def _format_points(val, decimals=2):
    if val is None:
        return "-"
    try:
        val_float = float(val)
        return f"{val_float:,.{decimals}f} pts"
    except Exception:
        return f"{val} pts"


class MarketSummaryAPIView(APIView):
    """
    Return market data formatted in Indian Rupees (INR) for the 4 core groups:
    1. NIFTY 50 & SENSEX (Indices in Points)
    2. Gold & Silver (Metals in INR per gram / 10g / kg)
    3. Crude Oil & USD/INR (Macro energy in INR per barrel & Forex rate)
    4. Bitcoin (Crypto in INR & USD)
    """

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "date",
                OpenApiTypes.DATE,
                OpenApiParameter.QUERY,
                description="Snapshot date in YYYY-MM-DD format",
            ),
            OpenApiParameter(
                "category",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description="Filter by category: 'indices', 'metals', 'macro', or 'crypto'",
            ),
            OpenApiParameter(
                "symbol",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description="Filter by symbol/alias: 'nifty', 'sensex', 'gold', 'silver', 'crude', 'usdinr', 'bitcoin'",
            ),
        ],
        responses=MarketSummarySerializer,
    )
    def get(self, request):
        date_value = request.GET.get("date")
        if date_value:
            try:
                snapshot_date = datetime.fromisoformat(date_value).date()
            except Exception:
                return Response(
                    {"error": "invalid date"}, status=status.HTTP_400_BAD_REQUEST
                )
            snapshot = MarketSnapshot.objects.filter(
                snapshot_date=snapshot_date
            ).first()
            if snapshot is None:
                return Response(
                    {"error": "snapshot not found"}, status=status.HTTP_404_NOT_FOUND
                )
        else:
            snapshot = MarketSnapshot.objects.order_by(
                "-snapshot_date", "-created_at"
            ).first()
            if snapshot is None:
                return Response(
                    {"error": "snapshot not available"}, status=status.HTTP_404_NOT_FOUND
                )

        usd_inr = snapshot.usd_inr_rate or Decimal("83.95")
        gold_usd = snapshot.gold_price  # USD per gram
        silver_usd = snapshot.silver_price  # USD per gram
        crude_usd = snapshot.crude_oil_price  # USD per barrel
        btc_usd = snapshot.bitcoin_price  # USD
        nifty = snapshot.nifty_50_value  # Points
        sensex = snapshot.sensex_value  # Points

        # In INR conversions
        gold_inr_per_gram = (gold_usd * usd_inr) if (gold_usd and usd_inr) else None
        gold_inr_per_10g = (gold_inr_per_gram * 10) if gold_inr_per_gram else None

        silver_inr_per_gram = (silver_usd * usd_inr) if (silver_usd and usd_inr) else None
        silver_inr_per_kg = (silver_inr_per_gram * 1000) if silver_inr_per_gram else None

        crude_inr_per_barrel = (crude_usd * usd_inr) if (crude_usd and usd_inr) else None
        btc_inr = (btc_usd * usd_inr) if (btc_usd and usd_inr) else None

        indices_data = {
            "nifty_50": {
                "symbol": "^NSEI",
                "name": "NIFTY 50",
                "category": "indices",
                "value": nifty,
                "unit": "points",
                "formatted": _format_points(nifty),
            },
            "sensex": {
                "symbol": "^BSESN",
                "name": "SENSEX",
                "category": "indices",
                "value": sensex,
                "unit": "points",
                "formatted": _format_points(sensex),
            },
        }

        metals_data = {
            "gold": {
                "symbol": "GC=F",
                "name": "Gold (24K)",
                "category": "metals",
                "currency": "INR",
                "price_per_gram_inr": round(gold_inr_per_gram, 2) if gold_inr_per_gram else None,
                "price_per_10g_inr": round(gold_inr_per_10g, 2) if gold_inr_per_10g else None,
                "price_per_gram_usd": round(gold_usd, 4) if gold_usd else None,
                "formatted": f"{_format_inr(gold_inr_per_10g)} / 10g" if gold_inr_per_10g else _format_inr(gold_inr_per_gram),
            },
            "silver": {
                "symbol": "SI=F",
                "name": "Silver",
                "category": "metals",
                "currency": "INR",
                "price_per_gram_inr": round(silver_inr_per_gram, 2) if silver_inr_per_gram else None,
                "price_per_kg_inr": round(silver_inr_per_kg, 2) if silver_inr_per_kg else None,
                "price_per_gram_usd": round(silver_usd, 4) if silver_usd else None,
                "formatted": f"{_format_inr(silver_inr_per_kg)} / kg" if silver_inr_per_kg else _format_inr(silver_inr_per_gram),
            },
        }

        macro_data = {
            "crude_oil": {
                "symbol": "CL=F",
                "name": "Crude Oil (WTI)",
                "category": "macro",
                "currency": "INR",
                "value_inr": round(crude_inr_per_barrel, 2) if crude_inr_per_barrel else None,
                "value_usd": round(crude_usd, 2) if crude_usd else None,
                "formatted": f"{_format_inr(crude_inr_per_barrel)} / barrel" if crude_inr_per_barrel else "-",
            },
            "usd_inr": {
                "symbol": "USDINR=X",
                "name": "USD / INR",
                "category": "macro",
                "currency": "INR",
                "value_inr": round(usd_inr, 2) if usd_inr else None,
                "formatted": _format_inr(usd_inr),
            },
        }

        crypto_data = {
            "bitcoin": {
                "symbol": "BTC-USD",
                "name": "Bitcoin",
                "category": "crypto",
                "currency": "INR",
                "price_in_inr": round(btc_inr, 2) if btc_inr else None,
                "price_in_usd": round(btc_usd, 2) if btc_usd else None,
                "formatted": _format_inr(btc_inr),
            }
        }

        # Category filter
        category_param = (request.GET.get("category") or "").lower().strip()
        if category_param:
            if category_param in ("indices", "index"):
                return Response(
                    {"snapshot_date": snapshot.snapshot_date, "currency": "INR", "data": indices_data}
                )
            if category_param in ("metals", "commodities", "gold_silver"):
                return Response(
                    {"snapshot_date": snapshot.snapshot_date, "currency": "INR", "data": metals_data}
                )
            if category_param in ("macro", "energy_forex", "oil_forex"):
                return Response(
                    {"snapshot_date": snapshot.snapshot_date, "currency": "INR", "data": macro_data}
                )
            if category_param in ("crypto", "bitcoin"):
                return Response(
                    {"snapshot_date": snapshot.snapshot_date, "currency": "INR", "data": crypto_data}
                )
            return Response(
                {
                    "error": f"Unknown category '{category_param}'. Valid options: indices, metals, macro, crypto"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Symbol filter
        symbol_param = (request.GET.get("symbol") or "").lower().strip()
        if symbol_param:
            lookup = {
                "nifty": indices_data["nifty_50"],
                "^nsei": indices_data["nifty_50"],
                "sensex": indices_data["sensex"],
                "^bsesn": indices_data["sensex"],
                "gold": metals_data["gold"],
                "gc=f": metals_data["gold"],
                "silver": metals_data["silver"],
                "si=f": metals_data["silver"],
                "crude": macro_data["crude_oil"],
                "oil": macro_data["crude_oil"],
                "cl=f": macro_data["crude_oil"],
                "usdinr": macro_data["usd_inr"],
                "usdinr=x": macro_data["usd_inr"],
                "bitcoin": crypto_data["bitcoin"],
                "btc": crypto_data["bitcoin"],
                "btc-usd": crypto_data["bitcoin"],
            }
            if symbol_param in lookup:
                return Response(
                    {"snapshot_date": snapshot.snapshot_date, "asset": lookup[symbol_param]}
                )
            return Response(
                {"error": f"Symbol '{symbol_param}' not found in market summary"},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "snapshot_date": snapshot.snapshot_date,
                "currency": "INR",
                "usd_inr_rate": round(usd_inr, 4) if usd_inr else None,
                "indices": indices_data,
                "metals": metals_data,
                "macro": macro_data,
                "crypto": crypto_data,
            }
        )



class EmailSubscriberCreateAPIView(APIView):
    """Create or reactivate a subscriber for the daily email."""

    @extend_schema(
        request=EmailSubscriberSerializer, responses=EmailSubscriberSerializer
    )
    def post(self, request):
        serializer = EmailSubscriberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        subscriber, created = upsert_subscriber(
            name=serializer.validated_data["name"],
            email=serializer.validated_data["email"],
            mobile_number=serializer.validated_data.get("mobile_number"),
            source=serializer.validated_data.get("source"),
            interests=serializer.validated_data.get("interests"),
        )
        response_serializer = EmailSubscriberSerializer(subscriber)
        return Response(
            {
                "message": "Subscription saved",
                "created": created,
                "subscriber": response_serializer.data,
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
            blog.id: blog for blog in BlogPost.objects.filter(id__in=featured_blog_ids)
        }
        ordered_blogs = [
            blogs_by_id[blog_id]
            for blog_id in featured_blog_ids
            if blog_id in blogs_by_id
        ]
        serializer = self.get_serializer(ordered_blogs, many=True)
        return Response(serializer.data)


class BlogPostDetailAPIView(RetrieveAPIView):
    """Return a single blog post."""

    queryset = BlogPost.objects.all()
    serializer_class = BlogPostSerializer


class ChatbotAPIView(APIView):
    """Single endpoint chatbot for finance Q&A and calculator responses."""

    @extend_schema(
        request=ChatbotRequestSerializer, responses=ChatbotResponseSerializer
    )
    def post(self, request):
        serializer = ChatbotRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = process_chatbot_message(
            message=serializer.validated_data["message"],
            session_id=serializer.validated_data.get("session_id") or None,
            language=serializer.validated_data.get("language") or None,
        )
        return Response(result, status=status.HTTP_200_OK)


class MutualFundPerformanceListAPIView(ListAPIView):
    """Return mutual fund performance data filtered by category."""

    serializer_class = MutualFundPerformanceSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "category",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description="Category (e.g. Equity: ELSS)",
                required=False,
            ),
        ],
        responses=MutualFundPerformanceSerializer(many=True),
    )
    def get_queryset(self):
        category = self.request.query_params.get("category")
        if category:
            return MutualFundPerformance.objects.filter(category=category).order_by("scheme_name")
        return MutualFundPerformance.objects.all().order_by("scheme_name")


class MutualFundPerformanceCategoriesAPIView(APIView):
    """Return available mutual fund categories."""

    @extend_schema(
        responses=MutualFundCategorySerializer(many=True),
    )
    def get(self, request):
        categories = (
            MutualFundPerformance.objects.values_list("category", flat=True)
            .distinct()
            .order_by("category")
        )
        result = [
            {"category": cat, "periods": []}
            for cat in categories
            if cat
        ]
        return Response(result, status=status.HTTP_200_OK)
