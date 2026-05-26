# Solid Wealth Project Specification

## 1. Project Overview
Solid Wealth is a Django-based backend application focused on two core capabilities:

1. Fetching, parsing, storing, and serving AMFI mutual fund NAV data.
2. Managing email subscribers and sending a daily automated email to active subscribers.

The project currently functions as an API-first backend with scheduled background jobs. It does not include a frontend in this repository.

## 2. Technology Stack
- Django 6.0.5
- Django REST Framework
- PostgreSQL
- Celery
- Redis
- django-crontab
- django-cors-headers
- WhiteNoise
- python-dotenv
- requests

## 3. Project Structure
- `manage.py`: Django management entry point.
- `solidWealth/settings.py`: project settings, database, CORS, cron, email, and Celery configuration.
- `solidWealth/urls.py`: root URL routing.
- `solidWealth/celery.py`: Celery application bootstrap.
- `api/models.py`: database models.
- `api/serializers.py`: DRF serializers.
- `api/views.py`: API views and NAV parsing logic.
- `api/services.py`: service-layer business logic.
- `api/tasks.py`: Celery task wrapper.
- `api/urls.py`: app URL routing.
- `api/admin.py`: Django admin registrations.
- `api/tests.py`: current automated tests.
- `api/management/commands/fetch_nav.py`: manual NAV import command.
- `api/management/commands/send_daily_subscription_emails.py`: manual email queue command.

## 4. Implemented Features

### 4.1 Health Check
A simple health endpoint is available at `GET /api/health/` and returns a JSON status response.

### 4.2 NAV Ingestion and Storage
The app fetches the live AMFI NAV feed from `https://portal.amfiindia.com/spages/NAVAll.txt`, parses the text file, and stores the result in the `NavEntry` table.

Implemented behavior:
- Detects company heading lines.
- Skips header rows and malformed lines.
- Parses multiple date formats.
- Extracts scheme code, ISIN values, scheme name, NAV, and raw source line.
- Replaces previously stored NAV records after a successful fetch.

### 4.3 NAV API
The `GET /api/nav/` endpoint returns NAV entries with optional filters:
- `scheme_code`: exact match
- `q`: substring search in scheme name
- `date`: ISO date filter
- `limit`: result limit

If no database rows exist for the requested date, the API attempts to fetch and store fresh data. If persistence fails, it falls back to parsing the live feed in memory and returns filtered results directly.

### 4.4 Company NAV Summary API
The `GET /api/nav/company-summary/` endpoint groups NAV data by company and returns only regular-plan rows from the latest available feed.

Implemented behavior:
- Filters entries whose scheme name contains `regular`.
- Groups results by company name.
- Keeps only rows from the latest NAV date per company.
- Sorts rows by scheme name and scheme code.
- Supports optional `company_name` filtering.

### 4.5 Email Subscriber Management
The `POST /api/subscribers/` endpoint creates or reactivates a subscriber.

Implemented behavior:
- Validates input with DRF serializer.
- Normalizes name and email.
- Uses email as the unique identity.
- Reuses existing subscriber records when the same email is posted again.

### 4.6 Daily Email Sending
The project includes a background email flow for active subscribers.

Implemented behavior:
- Iterates over active subscribers.
- Sends a simple daily email message.
- Tracks sent and failed counts.
- Exposed through a Celery task and a Django management command.

### 4.7 Scheduling
Two automated cron jobs are configured:
- `fetch_nav` at `06:00 UTC` daily.
- `send_daily_subscription_emails` at `07:00 UTC` daily.

## 5. Data Models

### 5.1 `NavEntry`
Stores a single NAV record.

Fields:
- `scheme_code`
- `isin`
- `scheme_name`
- `nav`
- `repurchase_price`
- `sale_price`
- `nav_date`
- `raw_line`

Important behavior:
- Indexed by `scheme_code`, `isin`, `scheme_name`, `nav_date`.
- Also has a composite index on `scheme_code` and `nav_date`.

### 5.2 `EmailSubscriber`
Stores newsletter-style subscription data.

Fields:
- `name`
- `email`
- `is_active`
- `created_at`
- `updated_at`

Important behavior:
- Email is unique.
- Values are normalized before save.
- Ordering is by name.

## 6. API Endpoints

### 6.1 `GET /api/health/`
Returns:
```json
{ "status": "ok" }
```

### 6.2 `POST /api/subscribers/`
Creates or updates a subscriber.

Example payload:
```json
{
  "name": "Jane Doe",
  "email": "jane.doe@example.com"
}
```

### 6.3 `GET /api/nav/`
Optional query parameters:
- `scheme_code`
- `q`
- `date`
- `limit`

### 6.4 `GET /api/nav/company-summary/`
Optional query parameter:
- `company_name`

## 7. Service Flow

### 7.1 NAV Flow
1. Request hits the NAV API.
2. The code checks for data in the database.
3. If data is missing, it fetches the AMFI feed.
4. The text feed is parsed into structured rows.
5. Rows are stored in `NavEntry`.
6. The API returns serialized data.

### 7.2 Subscriber Flow
1. Client posts name and email.
2. Serializer validates the payload.
3. Service layer creates or updates the subscriber.
4. API returns the saved subscriber and whether it was newly created.

### 7.3 Daily Email Flow
1. Management command queues the Celery task.
2. Celery executes the task.
3. Service layer fetches all active subscribers.
4. Email is sent to each subscriber.
5. A summary of sent and failed emails is returned.

## 8. Testing Coverage
Current tests cover:
- Regular-plan company NAV grouping logic.
- Subscriber create/update behavior.
- Daily email sending through the management command.

## 9. Current Gaps and Notes
- The daily email body is still a placeholder.
- There is no frontend in this repository.
- NAV storage currently replaces the dataset instead of keeping a full historical archive.
- The project is prepared for asynchronous execution, but the operational Celery worker and Redis service must exist in the environment for background execution to run in production.

## 10. Summary
Solid Wealth is currently a backend system that combines live financial data ingestion with email subscription management. The implementation already includes API endpoints, database models, service-layer logic, Celery integration, cron scheduling, admin registration, and tests for the main workflows.
