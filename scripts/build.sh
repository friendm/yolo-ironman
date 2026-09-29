#!/usr/bin/env bash
# Render build step for the web service.
set -o errexit
pip install -r requirements.txt
python manage.py collectstatic --noinput
