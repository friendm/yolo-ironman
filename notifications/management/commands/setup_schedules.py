from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.utils import timezone
from django_q.models import Schedule

EASTERN = ZoneInfo("America/New_York")


def next_local(at, now=None):
    now = (now or timezone.now()).astimezone(EASTERN)
    candidate = datetime.combine(now.date(), at, tzinfo=EASTERN)
    if candidate <= now:
        candidate = datetime.combine(now.date() + timedelta(days=1), at, tzinfo=EASTERN)
    return candidate


class Command(BaseCommand):
    help = "Create or update the Django-Q2 schedules for the daily and hourly jobs."

    def handle(self, *args, **options):
        Schedule.objects.update_or_create(
            name="daily-7am-eastern",
            defaults={
                "func": "notifications.jobs.daily",
                "schedule_type": Schedule.DAILY,
                "next_run": next_local(time(7, 0)),
                "repeats": -1,
            },
        )
        Schedule.objects.update_or_create(
            name="hourly",
            defaults={
                "func": "notifications.jobs.hourly",
                "schedule_type": Schedule.HOURLY,
                "next_run": timezone.now().replace(minute=5, second=0, microsecond=0) + timedelta(hours=1),
                "repeats": -1,
            },
        )
        self.stdout.write(self.style.SUCCESS("Schedules are set."))
