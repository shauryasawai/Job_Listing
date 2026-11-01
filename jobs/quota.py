"""Daily caps on AI summaries. Counted from SummaryLog; the day resets at local midnight (TIME_ZONE)."""
from django.conf import settings
from django.utils import timezone

from .models import SummaryLog


def _day_start():
    return timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)


def quota_for(user):
    start = _day_start()
    todays = SummaryLog.objects.filter(created_at__gte=start)
    user_used = todays.filter(user=user).count() if getattr(user, "is_authenticated", False) else 0
    global_used = todays.count()
    user_cap, global_cap = settings.SUMMARY_DAILY_CAP_PER_USER, settings.SUMMARY_DAILY_CAP_GLOBAL
    return {
        "user_cap": user_cap, "user_used": user_used,
        "global_cap": global_cap, "global_used": global_used,
        "remaining": max(0, min(user_cap - user_used, global_cap - global_used)),
    }
