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
    list_display = ("name", "email", "mobile_number", "source", "is_active", "created_at")
    search_fields = ("name", "email", "mobile_number", "source")
    list_filter = ("source", "is_active", "created_at")


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
    list_display = ("category", "uploaded_at")
    list_filter = ("category",)
    fields = ("category", "file")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        file_path = obj.file.path
        detected_category = None
        rows_data = []

        try:
            # Check if file is .xls or .xlsx
            is_xls = file_path.lower().endswith(".xls")
            
            if is_xls:
                import xlrd
                wb = xlrd.open_workbook(file_path)
                sheet = wb.sheet_by_index(0)

                header_row_idx = None

                for r in range(sheet.nrows):
                    row_vals = [str(sheet.cell_value(r, c)).strip() for c in range(sheet.ncols)]
                    if not detected_category:
                        for c in range(len(row_vals)):
                            cell_str = row_vals[c].lower()
                            if "category:" in cell_str:
                                if c + 1 < len(row_vals) and row_vals[c + 1]:
                                    detected_category = str(sheet.cell_value(r, c + 1)).strip()
                                else:
                                    parts = str(sheet.cell_value(r, c)).split(":", 1)
                                    if len(parts) > 1 and parts[1].strip():
                                        detected_category = parts[1].strip()
                    if any("scheme name" in v.lower() for v in row_vals):
                        header_row_idx = r
                        break

                if header_row_idx is None:
                    from django.contrib import messages
                    messages.error(request, "Error: Could not find a row containing 'Scheme Name' in the Excel file.")
                    return

                row_main = [str(sheet.cell_value(header_row_idx, c)).strip() for c in range(sheet.ncols)]
                data_start_idx = header_row_idx + 1

                if header_row_idx + 1 < sheet.nrows:
                    row_sub = [str(sheet.cell_value(header_row_idx + 1, c)).strip() for c in range(sheet.ncols)]
                    # Check if subheader row has risk ratio names
                    if any(any(k in s.lower() for k in ["mean", "sharp", "alpha", "beta", "std"]) for s in row_sub):
                        data_start_idx = header_row_idx + 2
                        combined_headers = []
                        for c in range(sheet.ncols):
                            m = row_main[c]
                            s = row_sub[c]
                            if s:
                                combined_headers.append(s)
                            elif m:
                                combined_headers.append(m)
                            else:
                                combined_headers.append(f"col_{c}")
                        cols = combined_headers
                    else:
                        cols = row_main
                else:
                    cols = row_main

                for r in range(data_start_idx, sheet.nrows):
                    row_vals = [sheet.cell_value(r, c) for c in range(sheet.ncols)]
                    row_dict = {cols[c]: row_vals[c] for c in range(min(len(cols), len(row_vals)))}
                    scheme_name = str(row_dict.get("Scheme Name", "")).strip()
                    if not scheme_name or any(f in scheme_name.lower() for f in ["solid wealth", "corporate office", "disclaimer", "category average", "nifty 50", "note:"]):
                        continue
                    rows_data.append(row_dict)

            else:
                # Fallback / XLSX using pandas
                df_temp = pd.read_excel(file_path, header=None)
                header_row_idx = None
                for idx, row in df_temp.iterrows():
                    row_strs = [str(c).strip() for c in row.values]
                    if not detected_category:
                        for c_idx, cell_str in enumerate(row_strs):
                            if "category:" in cell_str.lower():
                                if c_idx + 1 < len(row_strs) and row_strs[c_idx + 1] and row_strs[c_idx + 1] != "nan":
                                    detected_category = row_strs[c_idx + 1]
                                else:
                                    parts = cell_str.split(":", 1)
                                    if len(parts) > 1 and parts[1].strip():
                                        detected_category = parts[1].strip()
                    if any("scheme name" in str(cell).lower() for cell in row.values):
                        header_row_idx = idx
                        break

                if header_row_idx is None:
                    from django.contrib import messages
                    messages.error(request, "Error: Could not find 'Scheme Name' in the Excel file.")
                    return

                # Check subheader
                if header_row_idx + 1 < len(df_temp):
                    sub_row = [str(c).strip() for c in df_temp.iloc[header_row_idx + 1].values]
                    if any(any(k in s.lower() for k in ["mean", "sharp", "alpha", "beta", "std"]) for s in sub_row):
                        main_row = [str(c).strip() for c in df_temp.iloc[header_row_idx].values]
                        cols = [sub_row[c] if sub_row[c] and sub_row[c] != "nan" else (main_row[c] if main_row[c] and main_row[c] != "nan" else f"col_{c}") for c in range(len(main_row))]
                        df = df_temp.iloc[header_row_idx + 2:].copy()
                        df.columns = cols
                    else:
                        df = pd.read_excel(file_path, header=header_row_idx)
                else:
                    df = pd.read_excel(file_path, header=header_row_idx)

                for _, row in df.iterrows():
                    row_dict = row.to_dict()
                    scheme_name = str(row_dict.get("Scheme Name", "")).strip()
                    if not scheme_name or scheme_name == "nan" or any(f in scheme_name.lower() for f in ["solid wealth", "corporate office", "disclaimer", "category average", "nifty 50", "note:"]):
                        continue
                    rows_data.append(row_dict)

        except Exception as e:
            from django.contrib import messages
            messages.error(request, f"Error reading Excel file: {e}")
            return

        final_category = (obj.category or detected_category or "Uncategorized").strip()
        if not obj.category and detected_category:
            obj.category = final_category
            obj.save(update_fields=["category"])

        MutualFundPerformance.objects.filter(category=final_category).delete()

        def safe_decimal(val):
            if val is None or pd.isna(val) or val == "" or str(val).strip() in ["-", "nan", "None", "NA", "N/A"]:
                return None
            try:
                # clean string formatting if any
                clean_val = str(val).replace(",", "").replace("%", "").strip()
                return Decimal(clean_val)
            except Exception:
                return None

        def safe_char(val):
            if val is None or pd.isna(val) or val == "" or str(val).strip() in ["-", "nan", "None", "NA", "N/A"]:
                return None
            return str(val).strip()

        def get_value_by_aliases(r_dict, *aliases):
            for a in aliases:
                for k, v in r_dict.items():
                    if k.lower().replace(" ", "").replace("_", "").replace(".", "") == a.lower().replace(" ", "").replace("_", "").replace(".", ""):
                        return v
            return None

        records = []
        for r_dict in rows_data:
            scheme_name = get_value_by_aliases(r_dict, "Scheme Name", "SchemeName", "Scheme")
            if not scheme_name or pd.isna(scheme_name):
                continue

            # Parse Launch Date
            raw_date = get_value_by_aliases(r_dict, "Launch Date", "LaunchDate", "Inception Date")
            parsed_date = None
            if raw_date and not pd.isna(raw_date):
                try:
                    if isinstance(raw_date, str):
                        for fmt in ["%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y"]:
                            try:
                                parsed_date = datetime.strptime(raw_date.strip(), fmt).date()
                                break
                            except Exception:
                                pass
                    elif hasattr(raw_date, "date"):
                        parsed_date = raw_date.date()
                    if not parsed_date:
                        parsed_date = pd.to_datetime(raw_date, dayfirst=True).date()
                except Exception:
                    pass

            sharpe_ratio = safe_decimal(get_value_by_aliases(r_dict, "Sharp Ratio", "Sharpe Ratio", "Sharpe", "Sharp"))
            rating = safe_char(get_value_by_aliases(r_dict, "Rating", "Performance Rating", "Rank Category"))

            # If rating is not provided in Excel, determine based on Sharpe Ratio
            if not rating and sharpe_ratio is not None:
                if sharpe_ratio >= Decimal("0.70"):
                    rating = "Top Performer"
                elif sharpe_ratio >= Decimal("0.45"):
                    rating = "Above Average Performer"
                else:
                    rating = "Average Performer"

            records.append(
                MutualFundPerformance(
                    category=final_category,
                    scheme_name=str(scheme_name).strip(),
                    nav=safe_decimal(get_value_by_aliases(r_dict, "NAV", "Net Asset Value")),
                    launch_date=parsed_date,
                    aum_crore=safe_decimal(get_value_by_aliases(r_dict, "AUM (Crore)", "AUM(Crore)", "AUM", "AUM Cr")),
                    ber_percent=safe_decimal(get_value_by_aliases(r_dict, "BER (%)", "BER(%)", "BER")),
                    ter_percent=safe_decimal(get_value_by_aliases(r_dict, "TER (%)", "TER(%)", "TER")),
                    rating=rating,
                    return_1yr=safe_decimal(get_value_by_aliases(r_dict, "1 Yr Rtn (%)", "1 Yr Return (%)", "1 Yr Rtn", "1 Yr", "1 Year Return")),
                    return_3yr=safe_decimal(get_value_by_aliases(r_dict, "3 Yrs Rtn (%)", "3 Yrs Return (%)", "3 Yrs Rtn", "3 Yrs", "3 Year Return")),
                    return_5yr=safe_decimal(get_value_by_aliases(r_dict, "5 Yrs Rtn (%)", "5 Yrs Return (%)", "5 Yrs Rtn", "5 Yrs", "5 Year Return")),
                    return_10yr=safe_decimal(get_value_by_aliases(r_dict, "10 Yrs Rtn (%)", "10 Yrs Return (%)", "10 Yrs Rtn", "10 Yrs", "10 Year Return")),
                    mean=safe_decimal(get_value_by_aliases(r_dict, "Mean")),
                    sharpe_ratio=sharpe_ratio,
                    alpha=safe_decimal(get_value_by_aliases(r_dict, "Alpha")),
                    beta=safe_decimal(get_value_by_aliases(r_dict, "Beta")),
                    std_deviation=safe_decimal(get_value_by_aliases(r_dict, "Std. Deviation", "Std Deviation", "Std Dev", "Standard Deviation")),
                    fund_manager=safe_char(get_value_by_aliases(r_dict, "Fund Manager", "Manager")),
                )
            )

        MutualFundPerformance.objects.bulk_create(records)
        from django.contrib import messages
        messages.success(request, f"Successfully uploaded and extracted {len(records)} mutual funds for '{final_category}'.")


@admin.register(MutualFundPerformance)
class MutualFundPerformanceAdmin(admin.ModelAdmin):
    list_display = ("scheme_name", "category", "rating", "return_1yr", "return_3yr", "sharpe_ratio", "alpha")
    search_fields = ("scheme_name", "category", "rating")
    list_filter = ("category", "rating")
