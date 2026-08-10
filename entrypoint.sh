#!/bin/bash

echo "Apply database migrations"
python manage.py migrate

python manage.py collectstatic --noinput

echo "Setting up crontab"
python manage.py crontab add

echo "Starting cron"
service cron start

echo "Starting server"
exec gunicorn solidWealth.wsgi:application --bind 0.0.0.0:8000
