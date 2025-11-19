import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError

from orders.models import EmailLog, Order

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
