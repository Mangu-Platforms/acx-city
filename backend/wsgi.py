"""Production WSGI entrypoint.

Run with a real server instead of the Flask dev server, e.g.:
    gunicorn --bind 0.0.0.0:5000 --workers 2 --threads 4 --timeout 3600 wsgi:app
"""
from app import app

__all__ = ["app"]
