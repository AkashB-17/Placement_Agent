"""
College-wide settings an admin changes from the app, stored in the app_settings table.

The only one so far is the auto-apply threshold: the minimum score for auto-apply and
for the "auto-apply recommended" flag on /match and /ranked. Students can set their own
bar only at or above it. Until an admin sets it, AUTO_APPLY_THRESHOLD (config) is used.

Every reader goes through auto_apply_threshold(), so a change applies everywhere at once:
rankings, the per-student flag, auto-apply runs and the students' preference form.
On Postgres the value is cached for a few seconds (ranking reads it once per student);
SQLite is local, so it's read directly, which also keeps tests independent.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from app import db
from app.config import get_settings

THRESHOLD_KEY = "auto_apply_threshold"
CACHE_SECONDS = 10.0
_cache: dict[str, tuple[float, Any]] = {}


def _stored(key: str) -> dict[str, Any] | None:
    if not db.using_postgres():
        return db.get_app_setting(key)
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    value = db.get_app_setting(key)
    _cache[key] = (now + CACHE_SECONDS, value)
    return value


def auto_apply_threshold() -> float:
    stored = _stored(THRESHOLD_KEY)
    return float(stored["value"]) if stored else get_settings().auto_apply_threshold


def threshold_info() -> dict[str, Any]:
    stored = _stored(THRESHOLD_KEY)
    return {
        "auto_apply_threshold": float(stored["value"]) if stored else get_settings().auto_apply_threshold,
        "default_auto_apply_threshold": get_settings().auto_apply_threshold,
        "updated_at": stored["updated_at"] if stored else None,
    }


def set_auto_apply_threshold(value: float, updated_by: str | None) -> None:
    db.set_app_setting(THRESHOLD_KEY, round(float(value), 2), datetime.now(UTC), updated_by)
    _cache.pop(THRESHOLD_KEY, None)
