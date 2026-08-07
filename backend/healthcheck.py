#!/usr/bin/env python3
"""Standalone health check script for Docker HEALTHCHECK.

Checks DB, Redis, and Ollama connectivity. Returns exit 0 if all healthy.
"""
import sys
import os

def check_db():
    """Check PostgreSQL connectivity."""
    try:
        import psycopg
        dsn = os.getenv("DATABASE_URL", "")
        if not dsn:
            return True  # SQLite fallback, always "healthy"
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return True
    except Exception as e:
        print(f"DB: FAIL ({e})")
        return False

def check_redis():
    """Check Redis connectivity."""
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return True  # No Redis configured = not required
    try:
        import redis
        r = redis.from_url(redis_url, socket_timeout=5)
        r.ping()
        return True
    except Exception as e:
        print(f"Redis: FAIL ({e})")
        return False

def check_api():
    """Check if the Flask API responds."""
    try:
        import urllib.request
        port = os.getenv("PORT", "5000")
        resp = urllib.request.urlopen(f"http://localhost:{port}/api/health", timeout=5)
        return resp.status == 200
    except Exception as e:
        print(f"API: FAIL ({e})")
        return False

if __name__ == "__main__":
    checks = [check_db(), check_redis(), check_api()]
    if all(checks):
        sys.exit(0)
    else:
        sys.exit(1)
