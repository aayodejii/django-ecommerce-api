from rest_framework import viewsets, permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db import transaction

from .models import Product, Order, OrderItem
from .serializers import ProductSerializer, OrderSerializer, OrderItemSerializer


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.filter(is_active=True)
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save()


class OrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return (
                Order.objects.all()
                .select_related("user")
                .prefetch_related("items__product")
            )
        return (
            Order.objects.filter(user=user)
            .select_related("user")
            .prefetch_related("items__product")
        )

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["post"], url_path="update-status")
    def update_status(self, request, pk=None):
        order = self.get_object()
        new_status = request.data.get("status")
        if new_status not in dict(Order.STATUS_CHOICES):
            return Response({"error": "Invalid status"}, status=400)
        order.status = new_status
        order.save(update_fields=["status"])
        return Response(OrderSerializer(order, context={"request": request}).data)


class OrderItemViewSet(viewsets.ModelViewSet):
    serializer_class = OrderItemSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return OrderItem.objects.all().select_related("order", "product")
        return OrderItem.objects.filter(order__user=user).select_related(
            "order", "product"
        )

    @transaction.atomic
    def perform_create(self, serializer):
        serializer.save()
        serializer.instance.order.calculate_total()
