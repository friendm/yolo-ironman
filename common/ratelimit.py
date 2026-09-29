"""Fixed-window rate limiting backed by the Django cache (database cache in production)."""

import time

from django.core.cache import cache


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def hit(scope, key, limit, window_seconds):
    """Record one attempt; return True while the caller is within the limit."""
    bucket = int(time.time() // window_seconds)
    cache_key = f"rl:{scope}:{key}:{bucket}"
    added = cache.add(cache_key, 1, timeout=window_seconds + 5)
    if added:
        return True
    try:
        count = cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, 1, timeout=window_seconds + 5)
        count = 1
    return count <= limit
