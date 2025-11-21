import uuid

# import logging

from django.core.cache import cache
from django.db import transaction
from rest_framework import serializers

from orders.models import Order, OrderItem, Product
from orders.tasks import send_order_confirmation_email
from orders.utils.logging import logger

# logger = logging.getLogger(__name__)


class OrderItemInputSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)

    def validate_product_id(self, value):
        if not Product.objects.filter(id=value, is_active=True).exists():
            raise serializers.ValidationError(
                f"Product {value} does not exist or is inactive"
            )
        return value


class OrderItemSerializer(serializers.ModelSerializer):
    subtotal = serializers.SerializerMethodField()
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = OrderItem
        fields = [
            "id",
            "order",
            "product",
            "product_name",
            "quantity",
            "price",
            "subtotal",
        ]
        read_only_fields = ["id", "price", "subtotal"]

    def get_subtotal(self, obj):
        return obj.subtotal


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "user",
            "total",
            "status",
            "payment_status",
            "payment_reference",
            "created_at",
            "updated_at",
            "items",
        ]
        read_only_fields = ["id", "total", "created_at", "updated_at", "user"]


class OrderCreateSerializer(serializers.ModelSerializer):
    items = OrderItemInputSerializer(many=True, write_only=True)

    class Meta:
        model = Order
        fields = ["id", "user", "total", "status", "created_at", "updated_at", "items"]
        read_only_fields = ["id", "total", "created_at", "updated_at", "user"]

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("Order must have at least one item")
        return value

    def create(self, validated_data):
        import time

        start_time = time.time()
        request_id = str(uuid.uuid4())
        items_data = validated_data.pop("items")
        product_ids = [item["product_id"] for item in items_data]

        logger.info(
            "Order creation started",
            extra={
                "request_id": request_id,
                "user_id": validated_data["user"].id,
                "product_count": len(items_data),
                "action": "order_create_start",
            },
        )

        locks_acquired = []

        try:
            for product_id in product_ids:
                lock_key = f"product_lock:{product_id}"
                lock = cache.lock(lock_key, timeout=10, blocking_timeout=5)

                acquired = lock.acquire(blocking=True)
                if not acquired:
                    logger.warning(
                        "Failed to acquire lock",
                        extra={
                            "request_id": request_id,
                            "product_id": str(product_id),
                            "action": "lock_failed",
                        },
                    )
                    raise serializers.ValidationError(
                        "Product is currently being ordered. Please try again."
                    )
                locks_acquired.append(lock)

            with transaction.atomic():
                products = {p.id: p for p in Product.objects.filter(id__in=product_ids)}

                for item_data in items_data:
                    product = products[item_data["product_id"]]
                    quantity = item_data["quantity"]

                    if product.stock_quantity < quantity:
                        logger.warning(
                            "Insufficient stock",
                            extra={
                                "request_id": request_id,
                                "product_id": str(product.id),
                                "product_name": product.name,
                                "available": product.stock_quantity,
                                "requested": quantity,
                                "action": "stock_check_failed",
                            },
                        )
                        raise serializers.ValidationError(
                            f"Not enough stock for {product.name}. "
                            f"Available: {product.stock_quantity}, Requested: {quantity}"
                        )

                payment_reference = f"ORD-{uuid.uuid4().hex[:12].upper()}"
                order = Order.objects.create(
                    **validated_data, payment_reference=payment_reference
                )

                total = 0
                for item_data in items_data:
                    product = products[item_data["product_id"]]
                    quantity = item_data["quantity"]
                    price = product.price

                    product.stock_quantity -= quantity
                    product.save(update_fields=["stock_quantity"])

                    OrderItem.objects.create(
                        order=order, product=product, quantity=quantity, price=price
                    )
                    total += price * quantity

                order.total = total
                order.save(update_fields=["total"])

                send_order_confirmation_email.delay(str(order.id))

                duration_ms = (time.time() - start_time) * 1000
                logger.info(
                    "Order created successfully",
                    extra={
                        "request_id": request_id,
                        "order_id": str(order.id),
                        "user_id": order.user.id,
                        "total": float(order.total),
                        "item_count": len(items_data),
                        "duration_ms": round(duration_ms, 2),
                        "action": "order_created",
                    },
                )

                return order

        except serializers.ValidationError:
            duration_ms = (time.time() - start_time) * 1000
            logger.info(
                "Order creation validation failed",
                extra={
                    "request_id": request_id,
                    "duration_ms": round(duration_ms, 2),
                    "action": "order_create_validation_failed",
                },
            )
            raise

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error(
                "Order creation failed",
                extra={
                    "request_id": request_id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "duration_ms": round(duration_ms, 2),
                    "action": "order_create_failed",
                },
            )
            raise

        finally:
            for lock in locks_acquired:
                try:
                    lock.release()
                except Exception as e:
                    logger.error(
                        "Failed to release lock",
                        extra={
                            "request_id": request_id,
                            "error": str(e),
                            "action": "lock_release_failed",
                        },
                    )


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ["id", "name", "stock_quantity", "price", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]
