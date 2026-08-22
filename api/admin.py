from decimal import Decimal

import pandas as pd
from django.contrib import admin

from .models import (
    BlogPost,
    EmailSubscriber,
    MarketSnapshot,
    MutualFundDataUpload,
    MutualFundPerformance,
    NavEntry,
)


@admin.register(NavEntry)
class NavEntryAdmin(admin.ModelAdmin):
    list_display = ("scheme_code", "scheme_name", "nav", "nav_date")
    search_fields = ("scheme_code", "scheme_name", "isin")
    list_filter = ("nav_date",)


@admin.register(EmailSubscriber)
class EmailSubscriberAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "is_active", "created_at")
    search_fields = ("name", "email")
    list_filter = ("is_active", "created_at")


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = ("heading", "blog_type", "created_at", "updated_at")
    search_fields = ("heading", "small_content", "full_content", "blog_type")
    list_filter = ("blog_type", "created_at", "updated_at")


@admin.register(MarketSnapshot)
class MarketSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "snapshot_date",
        "gold_price",
        "silver_price",
        "crude_oil_price",
        "bitcoin_price",
        "nifty_50_value",
        "sensex_value",
        "usd_inr_rate",
        "created_at",
    )
    search_fields = ("snapshot_date",)
    list_filter = ("snapshot_date", "created_at")


@admin.register(MutualFundDataUpload)
class MutualFundDataUploadAdmin(admin.ModelAdmin):
    list_display = ("category", "period", "uploaded_at")
    list_filter = ("category", "period")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        # Parse the excel file
        try:
            df = pd.read_excel(obj.file.path)
            # Read without header to search for the correct header row
            df_temp = pd.read_excel(obj.file.path, header=None)
            
            header_row_index = None
            for idx, row in df_temp.iterrows():
                # Check if any cell in this row contains "Scheme Name" (ignoring spaces)
                if any("Scheme Name" in str(cell).strip() for cell in row.values):
                    header_row_index = idx
                    break
            
            if header_row_index is None:
                from django.contrib import messages
                messages.error(request, f"Error: Could not find a row containing 'Scheme Name' anywhere in the Excel file.")
                return
                
            # Read the file again using the correct header row
            df = pd.read_excel(obj.file.path, header=header_row_index)
            
            # Robustly normalize column names:
            # 1. Convert to string
            # 2. Replace newlines with spaces (since Excel headers often use Alt+Enter)
            # 3. Replace '[' with '(' and ']' with ')' just in case
            # 4. Remove multiple consecutive spaces
            def normalize_header(col):
                c = str(col).replace('\n', ' ').replace('\r', ' ')
                c = c.replace('[', '(').replace(']', ')')
                return ' '.join(c.split())
                
            df.columns = [normalize_header(col) for col in df.columns]
            
        except Exception as e:
            from django.contrib import messages
            messages.error(request, f"Error reading Excel file: {e}")
            return

        # Delete old records
        MutualFundPerformance.objects.filter(
            category=obj.category, period=obj.period
        ).delete()

        def safe_decimal(val):
            if pd.isna(val) or val == "-":
                return None
            try:
                return Decimal(str(val).strip())
            except Exception:
                return None

        def safe_char(val):
            if pd.isna(val) or val == "-":
                return None
            return str(val).strip()

        records = []
        for index, row in df.iterrows():
            scheme_name = row.get("Scheme Name")
            if pd.isna(scheme_name) or str(scheme_name).strip() in [
                "Category Average",
                "NIFTY 50 TRI",
            ]:
                continue

            nav_date = None
            if "Launch Date" in row and not pd.isna(row["Launch Date"]):
                try:
                    nav_date = pd.to_datetime(row["Launch Date"]).date()
                except Exception:
                    pass

            records.append(
                MutualFundPerformance(
                    category=obj.category,
                    period=obj.period,
                    scheme_name=str(scheme_name).strip(),
                    nav=safe_decimal(row.get("NAV")),
                    launch_date=nav_date,
                    aum_crore=safe_decimal(row.get("AUM (Crore)")),
                    ber_percent=safe_decimal(row.get("BER (%)")),
                    ter_percent=safe_decimal(row.get("TER (%)")),
                    ytd_return=safe_decimal(row.get("YTD Rtn (%)")),
                    return_1w=safe_decimal(row.get("1 Wk Rtn (%)")),
                    return_1m=safe_decimal(row.get("1 Mon Rtn (%)")),
                    return_3m=safe_decimal(row.get("3 Mths Rtn (%)")),
                    return_6m=safe_decimal(row.get("6 Mths Rtn (%)")),
                    return_1yr=safe_decimal(row.get("1 Yr Rtn (%)")),
                    rank_1yr=safe_char(row.get("1 Yr Rank")),
                    return_2yr=safe_decimal(row.get("2 Yrs Rtn (%)")),
                    rank_2yr=safe_char(row.get("2 Yrs Rank")),
                    return_3yr=safe_decimal(row.get("3 Yrs Rtn (%)")),
                    rank_3yr=safe_char(row.get("3 Yrs Rank")),
                    return_5yr=safe_decimal(row.get("5 Yrs Rtn (%)")),
                    rank_5yr=safe_char(row.get("5 Yrs Rank")),
                    return_10yr=safe_decimal(row.get("10 Yrs Rtn (%)")),
                    rank_10yr=safe_char(row.get("10 Yrs Rank")),
                    fund_manager=safe_char(row.get("Fund Manager")),
                )
            )

        MutualFundPerformance.objects.bulk_create(records)


@admin.register(MutualFundPerformance)
class MutualFundPerformanceAdmin(admin.ModelAdmin):
    list_display = ("scheme_name", "category", "period", "return_1yr")
    search_fields = ("scheme_name", "category")
    list_filter = ("category", "period")
