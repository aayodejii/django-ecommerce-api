import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from orders.models import EmailLog, Order, WebhookEvent

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
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


@shared_task(bind=True, max_retries=3)
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
