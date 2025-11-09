from rest_framework import serializers
from .models import Product, Order, OrderItem


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "price",
            "stock_quantity",
            "created_at",
            "updated_at",
            "is_active",
        ]


class OrderItemSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    product_id = serializers.UUIDField(write_only=True)

    subtotal = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = [
            "id",
            "order",
            "product",
            "product_id",
            "quantity",
            "price",
            "subtotal",
        ]
        read_only_fields = ["id", "order", "subtotal"]

    def get_subtotal(self, obj):
        return obj.subtotal


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    user = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "user",
            "status",
            "total",
            "created_at",
            "updated_at",
            "items",
        ]
        read_only_fields = ["id", "total", "created_at", "updated_at"]

    def create(self, validated_data):
        """Custom create method to support nested order items creation"""
        request = self.context.get("request")
        user = request.user if request else None

        # Create order first
        order = Order.objects.create(user=user, **validated_data)

        # Handle nested items if provided
        items_data = self.initial_data.get("items", [])
        for item_data in items_data:
            product_id = item_data.get("product_id")
            quantity = item_data.get("quantity", 1)

            if not product_id:
                continue

            # Get product
            from .models import Product  # local import to avoid circular import

            product = Product.objects.get(id=product_id)

            # Create order item
            OrderItem.objects.create(
                order=order,
                product=product,
                quantity=quantity,
                price=product.price,
            )

        # Update total
        order.calculate_total()

        return order
