import logging
from datetime import timedelta

from celery import Task, shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, models, transaction
from django.db.models import Sum, Count
from django.utils import timezone

from orders.models import (
    OrderItem,
    Product,
    Order,
    WebhookEvent,
    EmailLog,
    DailySalesReport,
    LowStockAlert,
    WebhookCleanupLog,
    FailedTask,
)


logger = logging.getLogger(__name__)


class CallbackTask(Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        FailedTask.objects.create(
            task_name=self.name,
            task_id=task_id,
            args=args,
            kwargs=kwargs,
            exception=str(exc),
            traceback=str(einfo),
        )

        logger.error(f"Task {self.name} failed permanently: {exc}")

        super().on_failure(exc, task_id, args, kwargs, einfo)


@shared_task(bind=True, base=CallbackTask, max_retries=3)
def send_order_confirmation_email(self, order_id):
    try:
        order = (
            Order.objects.select_related("user")
            .prefetch_related("items__product")
            .get(id=order_id)
        )

        try:
            EmailLog.objects.create(order=order, email_type="order_confirmation")
        except IntegrityError:
            logger.info(f"Email already sent for order {order_id}, skipping")
            return f"Email already sent for order {order_id}"

        items_text = "\n".join(
            [
                f"- {item.product.name} x  {item.quantity} = ₦{item.subtotal}"
                for item in order.items.all()
            ]
        )

        message = f"""
            Hi {order.user.username},

            Your order #{order.id} has been successfully confirmed!

            Items:
            {items_text}

            Total: ₦{order.total}

            Thank you for your order.
        """

        send_mail(
            subject="Order Confirmation #{order.id}",
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[order.user.email],
            fail_silently=False,
        )

        logger.info(
            f"Order confirmation email sent for order #{order.id} to {order.user.email}"
        )
        return f"Email sent for order #{order.id}"

    except Order.DoesNotExist:
        logger.error(f"Order {order_id} not found.")
        raise

    except Exception as exc:
        logger.error(f"Failed to send email for order {order_id}: {exc}")
        raise self.retry(exc=exc, countdown=2**self.request.retries)


@shared_task(bind=True, base=CallbackTask, max_retries=3)
def process_payment_webhook(self, event_id, payment_reference, status, amount):
    try:
        with transaction.atomic():
            webhook_event, created = WebhookEvent.objects.get_or_create(
                event_id=event_id,
                defaults={
                    "event_type": "payment",
                    "payload": {
                        "payment_reference": payment_reference,
                        "status": status,
                        "amount": amount,
                    },
                },
            )

            if not created and webhook_event.processed:
                logger.info(f"Webhook event {event_id} already processed, skipping")
                return f"Webhook event {event_id} already processed"

            try:
                order = Order.objects.select_for_update().get(
                    payment_reference=payment_reference
                )

            except Order.DoesNotExist:
                logger.error(
                    f"Order with payment reference {payment_reference} not found"
                )
                webhook_event.processed = True
                webhook_event.processed_at = timezone.now()
                webhook_event.save()
                return f"Order not found for reference {payment_reference}"

            if status == "success":
                if order.payment_status != Order.PAYMENT_PAID:
                    order.payment_status = Order.PAYMENT_PAID
                    order.status = Order.STATUS_CONFIRMED
                    order.save(update_fields=["payment_status", "status"])
                    logger.info(f"Order {order.id} marked as paid")
                else:
                    logger.info(f"Order {order.id} already marked as paid")

            elif status == "failed":
                order.payment_status = Order.STATUS_PAYMENT_FAILED
                order.status = Order.STATUS_FAILED
                order.save(update_fields=["payment_status", "status"])
                logger.warning(f"Order {order.id} marked as payment failed")

            webhook_event.processed = True
            webhook_event.processed_at = timezone.now()
            webhook_event.save()

            return (
                f"Processed webhook event {event_id} for order {order.id} successfully"
            )

    except Exception as exc:
        logger.error(f"Failed to process webhook event {event_id}: {exc}")
        raise self.retry(exc=exc, countdown=2**self.request.retries)


@shared_task(bind=True, base=CallbackTask, max_retries=3)
def check_low_stock(self):
    try:
        low_stock_threshold = 10
        today = timezone.now().date()

        low_stock_products = Product.objects.filter(
            stock_quantity__lte=low_stock_threshold, is_active=True
        )

        if not low_stock_products.exists():
            logger.info("No low stock products found")
            return "No low stock products"

        new_alerts = []
        for product in low_stock_products:
            recent_alert = LowStockAlert.objects.filter(
                product=product, created_at__gte=timezone.now() - timedelta(days=1)
            ).first()

            if recent_alert:
                logger.info(f"Alert already sent for {product.name} in last 24h")
                continue

            alert = LowStockAlert.objects.create(
                product=product, stock_level=product.stock_quantity
            )
            new_alerts.append(alert)

        if not new_alerts:
            logger.info("All low stock alerts already sent")
            return "All alerts already sent"

        products_list = "\n".join(
            [
                f"- {alert.product.name}: {alert.stock_level} units remaining"
                for alert in new_alerts
            ]
        )

        message = f"""
        Low Stock Alert - {today}

        The following products are running low:

        {products_list}

        Please restock soon.
        """

        send_mail(
            subject=f"Low Stock Alert - {today}",
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[settings.ADMIN_EMAIL],
            fail_silently=False,
        )

        for alert in new_alerts:
            alert.alert_sent = True
            alert.sent_at = timezone.now()
            alert.save()

        logger.info(f"Low stock alert sent for {len(new_alerts)} products")
        return f"Alert sent for {len(new_alerts)} products"

    except Exception as exc:
        logger.error(f"Failed to check low stock: {exc}")
        raise self.retry(exc=exc, countdown=300)


@shared_task(bind=True, base=CallbackTask, max_retries=3)
def cleanup_old_webhooks(self):
    try:
        today = timezone.now().date()

        try:
            cleanup_log = WebhookCleanupLog.objects.create(run_date=today)
        except IntegrityError:
            logger.info(f"Webhook cleanup already ran for {today}")
            return f"Cleanup already completed for {today}"

        archive_cutoff = timezone.now() - timedelta(days=90)
        delete_cutoff = timezone.now() - timedelta(days=365)

        with transaction.atomic():
            to_archive = WebhookEvent.objects.filter(
                processed=True,
                created_at__lt=archive_cutoff,
                created_at__gte=delete_cutoff,
                archived_at__isnull=True,
            )

            archived_count = to_archive.update(archived_at=timezone.now())

            to_delete = WebhookEvent.objects.filter(
                processed=True, created_at__lt=delete_cutoff
            )

            deleted_count = to_delete.count()
            to_delete.delete()

            cleanup_log.archived_count = archived_count
            cleanup_log.deleted_count = deleted_count
            cleanup_log.status = "success"
            cleanup_log.save()

        logger.info(f"Archived {archived_count}, deleted {deleted_count} webhooks")
        return f"Archived {archived_count}, deleted {deleted_count}"

    except IntegrityError:
        return f"Cleanup already completed for {today}"

    except Exception as exc:
        if "cleanup_log" in locals():
            cleanup_log.status = "failed"
            cleanup_log.save()

        logger.error(f"Webhook cleanup failed: {exc}")
        raise self.retry(exc=exc, countdown=3600)


@shared_task(bind=True, base=CallbackTask, max_retries=3)
def generate_daily_sales_report(self):
    try:
        today = timezone.now().date()
        yesterday = today - timedelta(days=1)

        report, created = DailySalesReport.objects.get_or_create(
            date=yesterday, defaults={"status": "processing"}
        )

        if not created and report.status == "completed":
            logger.info(f"Report for {yesterday} already generated")
            return f"Report already exists for {yesterday}"

        report.status = "processing"
        report.save()

        with transaction.atomic():
            orders = Order.objects.filter(
                created_at__date=yesterday, payment_status=Order.PAYMENT_PAID
            )

            stats = orders.aggregate(
                total_orders=Count("id"), total_revenue=Sum("total")
            )

            report.total_orders = stats["total_orders"] or 0
            report.total_revenue = stats["total_revenue"] or 0
            report.status = "completed"
            report.generated_at = timezone.now()
            report.save()

            top_products = (
                OrderItem.objects.filter(
                    order__created_at__date=yesterday,
                    order__payment_status=Order.PAYMENT_PAID,
                )
                .values("product__name")
                .annotate(
                    quantity_sold=Sum("quantity"),
                    revenue=Sum(models.F("price") * models.F("quantity")),
                )
                .order_by("-revenue")[:5]
            )

            products_list = (
                "\n".join(
                    [
                        f"- {p['product__name']}: {p['quantity_sold']} sold (₦{p['revenue']})"
                        for p in top_products
                    ]
                )
                if top_products
                else "No sales"
            )

            message = f"""
            Daily Sales Report - {yesterday}

            Total Orders: {report.total_orders}
            Total Revenue: ₦{report.total_revenue}

            Top Products:
            {products_list}

            Report generated at: {report.generated_at}
            """

            send_mail(
                subject=f"Daily Sales Report - {yesterday}",
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[settings.ADMIN_EMAIL],
                fail_silently=False,
            )

        logger.info(f"Daily sales report generated for {yesterday}")
        return f"Report generated for {yesterday}"

    except Exception as exc:
        if "report" in locals():
            report.status = "failed"
            report.save()

        logger.error(f"Failed to generate sales report: {exc}")
        raise self.retry(exc=exc, countdown=300)


@shared_task
def monitor_failed_tasks():
    recent_failures = FailedTask.objects.filter(
        failed_at__gte=timezone.now() - timedelta(hours=1), retried=False
    )

    if recent_failures.count() > 5:
        failed_tasks_list = "\n".join(
            [f"- {ft.task_name}: {ft.exception[:100]}" for ft in recent_failures[:10]]
        )

        message = f"""
        ALERT: High Task Failure Rate

        {recent_failures.count()} tasks have failed in the last hour:

        {failed_tasks_list}

        Please investigate immediately.
        """

        send_mail(
            subject="ALERT: High Task Failure Rate",
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[settings.ADMIN_EMAIL],
            fail_silently=False,
        )

        logger.warning(f"Alert sent: {recent_failures.count()} task failures")
        return f"Alert sent for {recent_failures.count()} failures"

    return "No alerts needed"
