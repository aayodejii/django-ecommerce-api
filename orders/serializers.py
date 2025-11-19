import uuid
import logging

from django.core.cache import cache
from django.db import transaction
from rest_framework import serializers

from orders.models import Order, OrderItem, Product
from orders.tasks import send_order_confirmation_email

logger = logging.getLogger(__name__)


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
        items_data = validated_data.pop("items")
        product_ids = [item["product_id"] for item in items_data]

        locks_acquired = []

        try:
            for product_id in product_ids:
                lock_key = f"product_lock:{product_id}"
                lock = cache.lock(lock_key, timeout=10, blocking_timeout=5)

                acquired = lock.acquire(blocking=True)
                if not acquired:
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
                    product.save()

                    OrderItem.objects.create(
                        order=order, product=product, quantity=quantity, price=price
                    )
                    total += price * quantity

                order.total = total
                order.save()

                send_order_confirmation_email.delay(order.id)

                return order

        finally:
            for lock in locks_acquired:
                try:
                    lock.release()
                except Exception as e:
                    logger.error(f"Error releasing lock: {e}")


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ["id", "name", "stock_quantity", "price", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]
