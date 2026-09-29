#!/usr/bin/env bash
# Runs before each deploy goes live.
set -o errexit
python manage.py migrate --noinput
python manage.py createcachetable
python manage.py setup_schedules
