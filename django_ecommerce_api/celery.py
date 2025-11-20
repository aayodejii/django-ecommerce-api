import os

from celery import Celery
from celery.schedules import crontab


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_ecommerce_api.settings")

app = Celery("django_ecommerce_api")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


app.conf.beat_schedule = {
    "check-low-stock-every-day": {
        "task": "orders.tasks.check_low_stock",
        "schedule": crontab(hour=9, minute=0),
    },
    "cleanup-old-webhooks-weekly": {
        "task": "orders.tasks.cleanup_old_webhooks",
        "schedule": crontab(day_of_week=1, hour=2, minute=0),
    },
    "daily-sales-report": {
        "task": "orders.tasks.generate_daily_sales_report",
        "schedule": crontab(hour=8, minute=0),
    },
}
