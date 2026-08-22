import html
import logging
import os
import re
import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation

import requests
import yfinance as yf
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .models import EmailSubscriber, MarketSnapshot

DAILY_EMAIL_SUBJECT = "Your daily Solid Wealth update"
AMFI_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"
logger = logging.getLogger(__name__)
MARKET_TICKERS = {
    "gold_price": "GC=F",
    "silver_price": "SI=F",
    "crude_oil_price": "CL=F",
    "bitcoin_price": "BTC-USD",
    "nifty_50_value": "^NSEI",
    "sensex_value": "^BSESN",
    "usd_inr_rate": "USDINR=X",
}

def _try_parse_nav_date(date_text):
    value = (date_text or "").strip()
    for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return timezone.datetime.strptime(value, fmt).date()
        except Exception:
            continue
    return None


def _fetch_amfi_nav_snapshot(limit=10):
    resp = requests.get(AMFI_URL, timeout=30)
    resp.raise_for_status()

    company_rows = {}
    current_company = None

    for raw_line in resp.text.splitlines():
        line = (raw_line or "").strip()
        if not line:
            continue

        if "mutual fund" in line.lower() and ";" not in line:
            current_company = line
            continue

        if (
            ";" not in line
            or line.lower().startswith("scheme code")
            or not current_company
        ):
            continue

        parts = [part.strip() for part in line.split(";")]
        if len(parts) < 6:
            continue

        scheme_name = parts[3] if len(parts) > 3 else ""
        if "regular" not in scheme_name.lower():
            continue

        nav_value = parts[4] if len(parts) > 4 else ""
        nav_date = _try_parse_nav_date(parts[-1])
        if not nav_date:
            continue

        candidate = {
            "company_name": current_company,
            "scheme_name": scheme_name,
            "nav": nav_value,
            "nav_date": nav_date,
        }

        existing = company_rows.get(current_company)
        if existing is None or nav_date > existing["nav_date"]:
            company_rows[current_company] = candidate

    rows = sorted(company_rows.values(), key=lambda row: row["company_name"])
    return rows[:limit]


def _format_nav_snapshot_lines(rows):
    if not rows:
        return ["NAV data could not be fetched right now."]

    lines = [
        "Company | Scheme | NAV",
        "--- | --- | ---",
    ]
    for row in rows:
        lines.append(f"{row['company_name']} | {row['scheme_name']} | {row['nav']}")
    return lines


def _to_decimal(value):
    try:
        return Decimal(str(value)).quantize(Decimal("0.000001"))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _fetch_latest_market_value(ticker_symbol):
    ticker = yf.Ticker(ticker_symbol)
    history = ticker.history(period="10d", interval="1d")
    if history is None or history.empty or "Close" not in history:
        return None
    close_values = history["Close"].dropna()
    if close_values.empty:
        return None
    return _to_decimal(close_values.iloc[-1])


def _extract_latest_close_value(history, ticker_symbol):
    if history is None or history.empty:
        return None

    try:
        if getattr(history.columns, "nlevels", 1) > 1:
            ticker_history = history[ticker_symbol]
            if (
                ticker_history is None
                or ticker_history.empty
                or "Close" not in ticker_history
            ):
                return None
            close_values = ticker_history["Close"].dropna()
        else:
            if "Close" not in history:
                return None
            close_values = history["Close"].dropna()
    except Exception:
        return None

    if close_values.empty:
        return None
    return _to_decimal(close_values.iloc[-1])


def fetch_market_snapshot_values():
    values = {field_name: None for field_name in MARKET_TICKERS}
    ticker_symbols = list(MARKET_TICKERS.values())

    try:
        history = yf.download(
            tickers=" ".join(ticker_symbols),
            period="10d",
            interval="1d",
            group_by="ticker",
            progress=False,
            auto_adjust=False,
            threads=False,
        )
    except Exception:
        logger.exception("Failed to fetch batched market snapshot values")
        history = None

    if history is not None and not history.empty:
        for field_name, ticker_symbol in MARKET_TICKERS.items():
            values[field_name] = _extract_latest_close_value(history, ticker_symbol)

    if not any(value is not None for value in values.values()):
        for field_name, ticker_symbol in MARKET_TICKERS.items():
            try:
                values[field_name] = _fetch_latest_market_value(ticker_symbol)
            except Exception:
                logger.exception(
                    "Failed to fetch market snapshot value for %s", ticker_symbol
                )
                values[field_name] = None

    # Convert Troy Ounce prices to per-gram prices
    troy_oz = Decimal("31.1034768")
    for field in ["gold_price", "silver_price"]:
        if values.get(field) is not None:
            values[field] = (values[field] / troy_oz).quantize(Decimal("0.000001"))

    return values


def upsert_market_snapshot(snapshot_date=None):
    snapshot_date = snapshot_date or timezone.localdate()
    values = fetch_market_snapshot_values()
    if not any(value is not None for value in values.values()):
        raise ValueError("No market snapshot values could be fetched")

    with transaction.atomic():
        MarketSnapshot.objects.exclude(snapshot_date=snapshot_date).delete()
        snapshot, created = MarketSnapshot.objects.update_or_create(
            snapshot_date=snapshot_date,
            defaults=values,
        )
    return snapshot, created


def upsert_subscriber(name, email, mobile_number=None):
    subscriber, created = EmailSubscriber.objects.update_or_create(
        email=(email or "").strip().lower(),
        defaults={
            "name": (name or "").strip(),
            "mobile_number": (
                re.sub(r"\s+", " ", (mobile_number or "")).strip() or None
            ),
            "is_active": True,
        },
    )
    return subscriber, created


def build_daily_email_body(subscriber, nav_rows=None, report_date=None):
    report_date = report_date or timezone.localdate()
    name = subscriber.name or "there"
    nav_rows = nav_rows or []

    lines = [
        f"Hello {name},",
        "",
        f'Here is your Solid Wealth report dated {report_date.strftime("%d %b %Y")}.',
        "",
        "NAV Snapshot (Top 10 different companies):",
    ]
    lines.extend(_format_nav_snapshot_lines(nav_rows))
    lines.extend(
        [
            "",
            "Visit SolidWealth: https://www.solidwealth.in/",
            "",
            "Regards,",
            "Solid Wealth Team",
        ]
    )

    return "\n".join(lines)


def build_daily_email_html(subscriber, nav_rows=None, report_date=None):
    report_date = report_date or timezone.localdate()
    name = html.escape(subscriber.name or "there")
    date_text = report_date.strftime("%d %b %Y")
    nav_rows = nav_rows or []

    if nav_rows:
        row_html = "\n".join(
            (
                "<tr>"
                f"<td style='padding:10px;border-bottom:1px solid #ffe4cc;color:#222;'>{html.escape(row['company_name'])}</td>"
                f"<td style='padding:10px;border-bottom:1px solid #ffe4cc;color:#222;'>{html.escape(row['scheme_name'])}</td>"
                f"<td style='padding:10px;border-bottom:1px solid #ffe4cc;color:#222;text-align:right;'>{html.escape(row['nav'])}</td>"
                "</tr>"
            )
            for row in nav_rows
        )
    else:
        row_html = (
            "<tr><td colspan='3' style='padding:12px;color:#666;text-align:center;'>"
            "NAV data could not be fetched right now."
            "</td></tr>"
        )

    return (
        "<div style='margin:0;padding:0;background:#fff7ef;font-family:Arial,Helvetica,sans-serif;color:#222;width:100%;'>"
        "<div style='width:100%;background:#ffffff;border:1px solid #ffd8b0;overflow:hidden;'>"
        "<div style='background:linear-gradient(90deg,#ff7a00 0%,#ff9c40 100%);padding:18px 24px;width:100%;box-sizing:border-box;'>"
        "<h2 style='margin:0;color:#ffffff;font-size:22px;line-height:1.2;'>Solid Wealth Daily Report</h2>"
        "</div>"
        "<div style='padding:24px;box-sizing:border-box;'>"
        f"<p style='margin:0 0 8px 0;font-size:16px;'>Hello <strong>{name}</strong>,</p>"
        f"<p style='margin:0 0 18px 0;color:#444;'>Here is your Solid Wealth report dated <strong>{date_text}</strong>.</p>"
        "<h3 style='margin:0 0 10px 0;color:#ff7a00;font-size:18px;'>NAV Snapshot (Top 10 different companies)</h3>"
        "<table style='width:100%;border-collapse:collapse;background:#fff;border:1px solid #ffd8b0;'>"
        "<thead><tr style='background:#fff1e3;'>"
        "<th style='padding:10px;text-align:left;color:#b45100;border-bottom:1px solid #ffd8b0;'>Company</th>"
        "<th style='padding:10px;text-align:left;color:#b45100;border-bottom:1px solid #ffd8b0;'>Scheme</th>"
        "<th style='padding:10px;text-align:right;color:#b45100;border-bottom:1px solid #ffd8b0;'>NAV</th>"
        "</tr></thead>"
        f"<tbody>{row_html}</tbody>"
        "</table>"
        "<p style='margin:16px 0 0 0;'>"
        "<a href='https://www.solidwealth.in/' style='color:#ff7a00;font-weight:700;text-decoration:none;'>Visit SolidWealth</a>"
        "</p>"
        "<p style='margin:18px 0 0 0;color:#555;'>Regards,<br><strong>Solid Wealth Team</strong></p>"
        "</div>"
        "</div>"
        "</div>"
    )


def send_daily_subscription_emails():
    subscribers = EmailSubscriber.objects.filter(is_active=True).order_by(
        "name", "email"
    )
    sent_count = 0
    failed_count = 0
    report_date = timezone.localdate()

    try:
        nav_rows = _fetch_amfi_nav_snapshot(limit=10)
    except Exception:
        nav_rows = []

    # Configure file logging for per-recipient results

    logger = logging.getLogger("solidwealth.email_sender")
    log_path = os.getenv("EMAIL_LOG_FILE")
    if log_path and not logger.handlers:
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
        except Exception:
            pass
        fh = logging.FileHandler(log_path)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)
        logger.setLevel(logging.INFO)

    for subscriber in subscribers:
        try:
            plain_message = build_daily_email_body(
                subscriber, nav_rows=nav_rows, report_date=report_date
            )
            html_message = build_daily_email_html(
                subscriber, nav_rows=nav_rows, report_date=report_date
            )
            send_mail(
                subject=DAILY_EMAIL_SUBJECT,
                message=plain_message,
                html_message=html_message,
                from_email=None,
                recipient_list=[subscriber.email],
                fail_silently=False,
            )
            sent_count += 1
            if logger:
                logger.info("SENT %s", subscriber.email)
        except Exception:
            failed_count += 1
            if logger:
                logger.exception("FAILED %s", subscriber.email)

    return {
        "total": subscribers.count(),
        "sent": sent_count,
        "failed": failed_count,
    }


FINANCIAL_DISCLAIMER = "The data is AI generated, check it before using it"
DEFAULT_SESSION_TTL_MINUTES = int(os.getenv("CHAT_SESSION_TTL_MINUTES", "15"))
SESSION_MEMORY = {}

DEFAULT_MODELS = {
    "groq": os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile"),
    "gemini": os.getenv("GEMINI_MODEL", "gemini-1.5-flash"),
    "openai": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
}

CALCULATOR_INTENTS = {
    "sip": ["sip", "systematic investment plan"],
    "step_up_sip": ["step up sip", "step-up sip", "stepup sip"],
    "lumpsum": ["lumpsum", "lump sum"],
    "emi": ["emi", "loan installment", "equated monthly"],
    "swp": ["swp", "systematic withdrawal"],
    "goal_based": ["goal", "target corpus", "goal based"],
    "retirement": ["retirement", "retire"],
    "inflation": ["inflation", "inflation-adjusted", "real return"],
    "cagr": ["cagr"],
    "xirr": ["xirr"],
    "fd_vs": ["fd vs", "fixed deposit vs", "fd compare"],
}


def _clean_amount_token(token):
    t = (token or "").lower().strip()
    t = t.replace("rs.", "").replace("rs", "").replace("inr", "").replace("₹", "")
    t = t.replace(",", "").strip()
    multiplier = 1.0
    if "crore" in t or "cr" in t:
        multiplier = 10000000.0
        t = t.replace("crores", "").replace("crore", "").replace("cr", "").strip()
    elif "lakh" in t or "lac" in t:
        multiplier = 100000.0
        t = t.replace("lakhs", "").replace("lakh", "").replace("lac", "").strip()
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
    patterns = patterns or [r"(\d+(?:\.\d+)?)\s*%"]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                continue
    return None


def _extract_years(text):
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*(years?|yrs?|yr|year|साल)", text, flags=re.IGNORECASE
    )
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return None
    return None


def _extract_months(text):
    m = re.search(r"(\d+(?:\.\d+)?)\s*(months?|mos?|month)", text, flags=re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return None
    return None


def _extract_all_numbers(text):
    vals = []
    for token in re.findall(r"₹?\s*[\d,]+(?:\.\d+)?", text):
        v = _clean_amount_token(token)
        if v is not None:
            vals.append(v)
    return vals


def _indian_number_format(value):
    neg = value < 0
    value = abs(float(value))
    whole, dec = f"{value:.2f}".split(".")
    if len(whole) > 3:
        last3 = whole[-3:]
        rest = whole[:-3]
        chunks = []
        while len(rest) > 2:
            chunks.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            chunks.insert(0, rest)
        whole = ",".join(chunks + [last3])
    formatted = f"₹{whole}.{dec}"
    return f"-{formatted}" if neg else formatted


def _detect_language(message):
    if re.search(r"[\u0900-\u097F]", message):
        return "hindi"
    hinglish_tokens = ["hai", "kya", "kitna", "sip", "paise", "saal", "mahina"]
    if any(tok in message.lower() for tok in hinglish_tokens):
        return "hinglish"
    return "english"


def _detect_intent(message):
    lower = message.lower()
    for intent, keywords in CALCULATOR_INTENTS.items():
        if any(keyword in lower for keyword in keywords):
            return intent
    financial_terms = [
        "investment",
        "return",
        "interest",
        "fund",
        "mutual",
        "loan",
        "finance",
    ]
    if any(term in lower for term in financial_terms):
        return "finance_general"
    return "general"


def _timing_mode(message):
    lower = message.lower()
    if any(
        k in lower
        for k in ["beginning", "start of month", "annuity due", "month start"]
    ):
        return "beginning"
    return "end"


def _emi_mode(message):
    lower = message.lower()
    if "flat" in lower:
        return "flat"
    return "reducing"


def _inflation_compounding_mode(message):
    lower = message.lower()
    if "monthly inflation" in lower or "monthly compounding" in lower:
        return "monthly"
    return "annual"


def _build_session_id():
    return uuid.uuid4().hex


def _purge_expired_sessions(now):
    expired = [sid for sid, data in SESSION_MEMORY.items() if data["expires_at"] <= now]
    for sid in expired:
        SESSION_MEMORY.pop(sid, None)


def _get_session(session_id=None):
    now = timezone.now()
    _purge_expired_sessions(now)
    if not session_id:
        session_id = _build_session_id()
    if session_id not in SESSION_MEMORY:
        SESSION_MEMORY[session_id] = {
            "history": [],
            "expires_at": now + timedelta(minutes=DEFAULT_SESSION_TTL_MINUTES),
        }
    else:
        SESSION_MEMORY[session_id]["expires_at"] = now + timedelta(
            minutes=DEFAULT_SESSION_TTL_MINUTES
        )
    return session_id, SESSION_MEMORY[session_id]


def _sip_future_value(
    monthly_investment, annual_rate, years, contribution_timing="end"
):
    r = annual_rate / 100.0 / 12.0
    n = int(round(years * 12))
    if n <= 0:
        return 0.0
    if abs(r) < 1e-9:
        fv = monthly_investment * n
    else:
        fv = monthly_investment * (((1 + r) ** n - 1) / r)
        if contribution_timing == "beginning":
            fv *= 1 + r
    return fv


def _lumpsum_future_value(principal, annual_rate, years):
    r = annual_rate / 100.0
    return principal * ((1 + r) ** years)


def _emi_value(principal, annual_rate, years, emi_type="reducing"):
    n = int(round(years * 12))
    if n <= 0:
        return 0.0
    if emi_type == "flat":
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


def _inflation_adjusted_future_value(
    present_value, inflation_rate, years, compounding="annual"
):
    if compounding == "monthly":
        r = inflation_rate / 100.0 / 12.0
        n = int(round(years * 12))
        return present_value * ((1 + r) ** n)
    r = inflation_rate / 100.0
    return present_value * ((1 + r) ** years)


def _step_up_sip_future_value(
    start_monthly, annual_return_rate, years, annual_step_up_rate
):
    months = int(round(years * 12))
    if months <= 0:
        return 0.0
    rm = annual_return_rate / 100.0 / 12.0
    current_sip = start_monthly
    fv = 0.0
    for month in range(1, months + 1):
        fv = (fv + current_sip) * (1 + rm)
        if month % 12 == 0:
            current_sip *= 1 + annual_step_up_rate / 100.0
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


def _required_monthly_for_goal(
    target_corpus, current_savings, annual_return_rate, years
):
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


def _retirement_projection(
    current_age, retirement_age, current_savings, monthly_investment, annual_return_rate
):
    years = retirement_age - current_age
    if years <= 0:
        return None, 0
    grown_current = _lumpsum_future_value(current_savings, annual_return_rate, years)
    grown_sip = _sip_future_value(
        monthly_investment, annual_return_rate, years, contribution_timing="end"
    )
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
        "annual_rate": annual_rate,
        "years": years,
        "months": _extract_months(text),
        "contribution_timing": _timing_mode(text),
        "emi_type": _emi_mode(text),
        "inflation_compounding": _inflation_compounding_mode(text),
    }

    if intent in ["sip", "step_up_sip"]:
        monthly = _extract_first_amount(
            message,
            [
                r"(?:monthly\s+investment|sip\s+amount|sip)\D*([₹\d,\.\s\w]+)",
                r"(?:invest\s+per\s+month|every\s+month)\D*([₹\d,\.\s\w]+)",
            ],
        )
        if monthly is None and numbers:
            monthly = numbers[0]
        inputs["monthly_investment"] = monthly
        if intent == "step_up_sip":
            step_rate = _extract_percentage(
                text,
                [
                    r"(\d+(?:\.\d+)?)\s*%\s*(?:step|increase|step up)",
                    r"step\s*up\D*(\d+(?:\.\d+)?)",
                ],
            )
            if step_rate is None and len(re.findall(r"(\d+(?:\.\d+)?)\s*%", text)) >= 2:
                step_rate = float(re.findall(r"(\d+(?:\.\d+)?)\s*%", text)[1])
            inputs["step_up_rate"] = step_rate

    if intent == "lumpsum":
        principal = _extract_first_amount(
            message,
            [r"(?:lumpsum|lump\s*sum|one\s*time\s*investment)\D*([₹\d,\.\s\w]+)"],
        )
        if principal is None and numbers:
            principal = numbers[0]
        inputs["principal"] = principal

    if intent == "emi":
        principal = _extract_first_amount(
            message, [r"(?:loan\s*amount|principal|loan)\D*([₹\d,\.\s\w]+)"]
        )
        if principal is None and numbers:
            principal = numbers[0]
        inputs["principal"] = principal

    if intent == "swp":
        corpus = _extract_first_amount(
            message,
            [r"(?:corpus|initial\s+corpus|starting\s+amount)\D*([₹\d,\.\s\w]+)"],
        )
        withdrawal = _extract_first_amount(
            message, [r"(?:withdrawal|monthly\s+withdrawal|withdraw)\D*([₹\d,\.\s\w]+)"]
        )
        if corpus is None and numbers:
            corpus = numbers[0]
        if withdrawal is None and len(numbers) > 1:
            withdrawal = numbers[1]
        inputs["initial_corpus"] = corpus
        inputs["monthly_withdrawal"] = withdrawal

    if intent == "goal_based":
        target = _extract_first_amount(
            message, [r"(?:target\s+corpus|target|goal)\D*([₹\d,\.\s\w]+)"]
        )
        current = _extract_first_amount(
            message,
            [
                r"(?:current\s+savings|existing\s+savings|current\s+amount)\D*([₹\d,\.\s\w]+)"
            ],
        )
        if target is None and numbers:
            target = numbers[0]
        if current is None and len(numbers) > 1:
            current = numbers[1]
        inputs["target_corpus"] = target
        inputs["current_savings"] = current if current is not None else 0.0

    if intent == "retirement":
        ages = re.findall(r"(\d{2})\s*(?:years?\s*old|yrs?\s*old|age)", text)
        if len(ages) >= 2:
            inputs["current_age"] = float(ages[0])
            inputs["retirement_age"] = float(ages[1])
        else:
            two_digit_numbers = [n for n in numbers if 18 <= n <= 80]
            if len(two_digit_numbers) >= 2:
                inputs["current_age"] = two_digit_numbers[0]
                inputs["retirement_age"] = two_digit_numbers[1]
        inputs["current_savings"] = _extract_first_amount(
            message, [r"(?:current\s+savings|existing\s+corpus)\D*([₹\d,\.\s\w]+)"]
        )
        inputs["monthly_investment"] = _extract_first_amount(
            message, [r"(?:monthly\s+investment|sip)\D*([₹\d,\.\s\w]+)"]
        )

    if intent == "inflation":
        present_value = _extract_first_amount(
            message,
            [
                r"(?:present\s+value|today\'?s\s+value|current\s+value|amount)\D*([₹\d,\.\s\w]+)"
            ],
        )
        if present_value is None and numbers:
            present_value = numbers[0]
        inputs["present_value"] = present_value

    if intent == "cagr":
        initial = _extract_first_amount(
            message,
            [r"(?:initial\s+value|initial\s+amount|start\s+value)\D*([₹\d,\.\s\w]+)"],
        )
        final = _extract_first_amount(
            message, [r"(?:final\s+value|final\s+amount|end\s+value)\D*([₹\d,\.\s\w]+)"]
        )
        if initial is None and numbers:
            initial = numbers[0]
        if final is None and len(numbers) > 1:
            final = numbers[1]
        inputs["initial_value"] = initial
        inputs["final_value"] = final

    if intent == "fd_vs":
        monthly = _extract_first_amount(
            message, [r"(?:monthly\s+investment|sip)\D*([₹\d,\.\s\w]+)"]
        )
        if monthly is None and numbers:
            monthly = numbers[0]
        inputs["monthly_investment"] = monthly
        fd_rate = _extract_percentage(
            text, [r"fd\D*(\d+(?:\.\d+)?)\s*%", r"(\d+(?:\.\d+)?)\s*%\s*fd"]
        )
        inputs["fd_rate"] = fd_rate

    return inputs


def _pretty_metric_label(key):
    return key.replace("_", " ").strip().title()


def _format_chatbot_response(
    answer, assumptions=None, metrics=None, follow_up_question="", disclaimer=None
):
    assumptions = assumptions or {}
    metrics = metrics or {}
    lines = [f"**Answer:** {answer}"]

    if metrics:
        lines.extend(["", "### Key points"])
        if "total_value" in metrics:
            lines.append(f"- Total value: {metrics['total_value']}")
        if "invested_amount" in metrics:
            lines.append(f"- Invested amount: {metrics['invested_amount']}")
        if "estimated_gain" in metrics:
            lines.append(f"- Estimated gain: {metrics['estimated_gain']}")
        if "monthly_emi" in metrics:
            lines.append(f"- Monthly EMI: {metrics['monthly_emi']}")
        if "remaining_corpus" in metrics:
            lines.append(f"- Remaining corpus: {metrics['remaining_corpus']}")
        if "required_monthly_investment" in metrics:
            lines.append(
                f"- Required monthly investment: {metrics['required_monthly_investment']}"
            )
        if "retirement_corpus" in metrics:
            lines.append(f"- Retirement corpus: {metrics['retirement_corpus']}")
        if "future_value" in metrics:
            lines.append(
                f"- Inflation-adjusted future value: {metrics['future_value']}"
            )
        if "cagr" in metrics:
            lines.append(f"- CAGR: {metrics['cagr']}")
        if "sip_projected_value" in metrics:
            lines.append(f"- SIP projected value: {metrics['sip_projected_value']}")
        if "fd_projected_value" in metrics:
            lines.append(f"- FD projected value: {metrics['fd_projected_value']}")

        lines.extend(["", "### Snapshot", "| Metric | Value |", "|---|---|"])
        for key, value in metrics.items():
            lines.append(f"| {_pretty_metric_label(key)} | {value} |")

    if assumptions:
        lines.extend(["", "### Assumptions"])
        for key, value in assumptions.items():
            lines.append(f"- {_pretty_metric_label(key)}: {value}")

    if follow_up_question:
        lines.extend(["", "### Next step", f"- {follow_up_question}"])

    if disclaimer:
        lines.extend(["", f"_{disclaimer}_"])

    return "\n".join(lines)


def _build_calculator_response(intent, inputs):
    if intent == "sip":
        required = ["monthly_investment", "annual_rate", "years"]
        if any(inputs.get(k) is None for k in required):
            return None
        total = _sip_future_value(
            inputs["monthly_investment"],
            inputs["annual_rate"],
            inputs["years"],
            inputs.get("contribution_timing") or "end",
        )
        invested = inputs["monthly_investment"] * int(round(inputs["years"] * 12))
        gain = total - invested
        return {
            "answer": f"Projected SIP value is {_indian_number_format(total)}.",
            "assumptions": {
                "contribution_timing": inputs.get("contribution_timing") or "end",
            },
            "metrics": {
                "total_value": _indian_number_format(total),
                "invested_amount": _indian_number_format(invested),
                "estimated_gain": _indian_number_format(gain),
            },
        }

    if intent == "step_up_sip":
        required = ["monthly_investment", "annual_rate", "years", "step_up_rate"]
        if any(inputs.get(k) is None for k in required):
            return None
        total = _step_up_sip_future_value(
            inputs["monthly_investment"],
            inputs["annual_rate"],
            inputs["years"],
            inputs["step_up_rate"],
        )
        return {
            "answer": f"Projected step-up SIP value is {_indian_number_format(total)}.",
            "assumptions": {"annual_step_up_rate": f"{inputs['step_up_rate']}%"},
            "metrics": {"total_value": _indian_number_format(total)},
        }

    if intent == "lumpsum":
        required = ["principal", "annual_rate", "years"]
        if any(inputs.get(k) is None for k in required):
            return None
        total = _lumpsum_future_value(
            inputs["principal"], inputs["annual_rate"], inputs["years"]
        )
        gain = total - inputs["principal"]
        return {
            "answer": f"Projected lumpsum value is {_indian_number_format(total)}.",
            "assumptions": {},
            "metrics": {
                "total_value": _indian_number_format(total),
                "invested_amount": _indian_number_format(inputs["principal"]),
                "estimated_gain": _indian_number_format(gain),
            },
        }

    if intent == "emi":
        required = ["principal", "annual_rate", "years"]
        if any(inputs.get(k) is None for k in required):
            return None
        emi_type = inputs.get("emi_type") or "reducing"
        emi = _emi_value(
            inputs["principal"],
            inputs["annual_rate"],
            inputs["years"],
            emi_type=emi_type,
        )
        n = int(round(inputs["years"] * 12))
        total_payment = emi * n
        return {
            "answer": f"Estimated monthly EMI is {_indian_number_format(emi)}.",
            "assumptions": {"emi_type": emi_type},
            "metrics": {
                "monthly_emi": _indian_number_format(emi),
                "total_payment": _indian_number_format(total_payment),
            },
        }

    if intent == "swp":
        required = ["initial_corpus", "monthly_withdrawal", "annual_rate", "years"]
        if any(inputs.get(k) is None for k in required):
            return None
        remaining = _swp_projection(
            inputs["initial_corpus"],
            inputs["monthly_withdrawal"],
            inputs["annual_rate"],
            inputs["years"],
        )
        return {
            "answer": f"Estimated corpus after SWP period is {_indian_number_format(remaining)}.",
            "assumptions": {},
            "metrics": {"remaining_corpus": _indian_number_format(remaining)},
        }

    if intent == "goal_based":
        required = ["target_corpus", "current_savings", "annual_rate", "years"]
        if any(inputs.get(k) is None for k in required):
            return None
        required_monthly = _required_monthly_for_goal(
            inputs["target_corpus"],
            inputs["current_savings"],
            inputs["annual_rate"],
            inputs["years"],
        )
        if required_monthly is None:
            return None
        return {
            "answer": f"Required monthly investment for your goal is {_indian_number_format(required_monthly)}.",
            "assumptions": {},
            "metrics": {
                "required_monthly_investment": _indian_number_format(required_monthly)
            },
        }

    if intent == "retirement":
        required = [
            "current_age",
            "retirement_age",
            "current_savings",
            "monthly_investment",
            "annual_rate",
        ]
        if any(inputs.get(k) is None for k in required):
            return None
        corpus, years = _retirement_projection(
            inputs["current_age"],
            inputs["retirement_age"],
            inputs["current_savings"],
            inputs["monthly_investment"],
            inputs["annual_rate"],
        )
        if corpus is None:
            return None
        return {
            "answer": f"Projected retirement corpus in {int(years)} years is {_indian_number_format(corpus)}.",
            "assumptions": {},
            "metrics": {"retirement_corpus": _indian_number_format(corpus)},
        }

    if intent == "inflation":
        required = ["present_value", "annual_rate", "years"]
        if any(inputs.get(k) is None for k in required):
            return None
        fv = _inflation_adjusted_future_value(
            inputs["present_value"],
            inputs["annual_rate"],
            inputs["years"],
            inputs.get("inflation_compounding") or "annual",
        )
        return {
            "answer": f"Inflation-adjusted future value is {_indian_number_format(fv)}.",
            "assumptions": {
                "compounding": inputs.get("inflation_compounding") or "annual"
            },
            "metrics": {"future_value": _indian_number_format(fv)},
        }

    if intent == "cagr":
        required = ["initial_value", "final_value", "years"]
        if any(inputs.get(k) is None for k in required):
            return None
        value = _cagr(inputs["initial_value"], inputs["final_value"], inputs["years"])
        if value is None:
            return None
        return {
            "answer": f"CAGR is {value:.2f}%.",
            "assumptions": {},
            "metrics": {"cagr": f"{value:.2f}%"},
        }

    if intent == "fd_vs":
        required = ["monthly_investment", "annual_rate", "fd_rate", "years"]
        if any(inputs.get(k) is None for k in required):
            return None
        sip_value = _sip_future_value(
            inputs["monthly_investment"], inputs["annual_rate"], inputs["years"]
        )
        fd_value = _sip_future_value(
            inputs["monthly_investment"], inputs["fd_rate"], inputs["years"]
        )
        recommendation = (
            "SIP projected value is higher."
            if sip_value > fd_value
            else "FD projected value is higher."
        )
        return {
            "answer": recommendation,
            "assumptions": {},
            "metrics": {
                "sip_projected_value": _indian_number_format(sip_value),
                "fd_projected_value": _indian_number_format(fd_value),
            },
        }

    if intent == "xirr":
        return None

    return None


def _build_system_prompt(language):
    lang = {
        "english": "English",
        "hindi": "Hindi",
        "hinglish": "Hinglish",
    }.get(language, "English")
    return (
        "You are an expert financial assistant and advisor. "
        "Your goal is to answer questions about finance, investment, mutual funds, SIP, EMI, etc., in a clear and educational way. "
        "If the user is asking to calculate something (like SIP, Lumpsum, or EMI) but has not provided all the necessary numbers, politely ask them to provide the missing values "
        "(e.g., for SIP ask for monthly investment, expected return rate, and time period). "
        "Be concise and practical, avoid guarantees, and do not provide unsafe promises. "
        f"Respond in {lang}. "
        "Use markdown with short bullet points. "
        "When numbers are involved, include a small markdown table for the key values. "
        "Only ask a follow-up question when more information is actually needed or the user explicitly asks for it."
    )


def _call_openai_like(api_url, api_key, model, messages):
    resp = requests.post(
        api_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "temperature": 0.2,
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _call_gemini(api_key, model, messages):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    joined = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
    payload = {
        "contents": [
            {
                "parts": [{"text": joined}],
            }
        ],
        "generationConfig": {"temperature": 0.2},
    }
    resp = requests.post(url, json=payload, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _llm_fallback_answer(message, language, history):
    system_prompt = _build_system_prompt(language)
    messages = [{"role": "system", "content": system_prompt}]
    for item in history[-10:]:
        messages.append({"role": item["role"], "content": item["content"]})
    messages.append({"role": "user", "content": message})

    providers = [
        ("groq", os.getenv("GROQ_API_KEY")),
        ("gemini", os.getenv("GEMINI_API_KEY")),
        ("openai", os.getenv("OPENAI_API_KEY")),
    ]

    for name, key in providers:
        if not key:
            continue
        try:
            if name == "groq":
                answer = _call_openai_like(
                    "https://api.groq.com/openai/v1/chat/completions",
                    key,
                    DEFAULT_MODELS["groq"],
                    messages,
                )
                return answer, "groq"
            if name == "gemini":
                answer = _call_gemini(key, DEFAULT_MODELS["gemini"], messages)
                return answer, "gemini"
            if name == "openai":
                answer = _call_openai_like(
                    "https://api.openai.com/v1/chat/completions",
                    key,
                    DEFAULT_MODELS["openai"],
                    messages,
                )
                return answer, "openai"
        except Exception:
            continue

    return (
        "I can help with SIP, Lumpsum, EMI, SWP, Goal, Retirement, Inflation, CAGR, XIRR, and FD comparisons. "
        "Please share exact values (amount, return rate, time period) so I can calculate accurately.",
        "none",
    )


def process_chatbot_message(message, session_id=None, language=None):
    session_id, session = _get_session(session_id=session_id)
    msg = (message or "").strip()
    lang = language or _detect_language(msg)
    intent = _detect_intent(msg)

    inputs = _extract_calculator_inputs(msg, intent)
    calculator_response = _build_calculator_response(intent, inputs)
    disclaimer = FINANCIAL_DISCLAIMER if intent != "general" else None
    provider_used = "rule-engine"

    if calculator_response is not None:
        answer = _format_chatbot_response(
            calculator_response["answer"],
            assumptions=calculator_response.get("assumptions") or {},
            metrics=calculator_response.get("metrics") or {},
            disclaimer=disclaimer,
        )
        explanation_short = (
            "This estimate is based on the inputs detected from your message."
        )
        assumptions = calculator_response.get("assumptions") or {}
        metrics = calculator_response.get("metrics") or {}
        follow_up = ""
    else:
        answer, provider_used = _llm_fallback_answer(msg, lang, session["history"])
        explanation_short = "Answer generated with advisor-style guidance and your recent session context."
        assumptions = {}
        metrics = {}
        answer = _format_chatbot_response(
            answer, follow_up_question="", disclaimer=disclaimer
        )
        follow_up = ""

    session["history"].append({"role": "user", "content": msg})
    session["history"].append({"role": "assistant", "content": answer})

    return {
        "session_id": session_id,
        "language_detected": lang,
        "intent": intent,
        "detected_inputs": {k: v for k, v in inputs.items() if v is not None},
        "assumptions": assumptions,
        "answer": answer,
        "explanation_short": explanation_short,
        "follow_up_question": follow_up,
        "metrics": metrics,
        "disclaimer": disclaimer,
        "provider_used": provider_used,
    }
