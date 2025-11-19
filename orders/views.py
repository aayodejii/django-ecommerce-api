import uuid

from django.shortcuts import get_object_or_404
from django.core.cache import cache
from rest_framework.views import APIView, status
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from django_ratelimit.decorators import ratelimit
from django.utils.decorators import method_decorator

from orders import serializers
from orders.models import Order, OrderItem, Product
from orders.tasks import process_payment_webhook


@method_decorator(ratelimit(key="user", rate="5/m", method="POST"), name="post")
class OrderAPIView(APIView):
    serializer_class = serializers.OrderSerializer
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id=None):
        if order_id:
            order = get_object_or_404(Order, id=order_id, user=request.user)
            serializer = serializers.OrderSerializer(order)
            return Response(status=status.HTTP_200_OK, data=serializer.data)

        orders = Order.objects.filter(user=request.user)
        serializer = self.serializer_class(orders, many=True)
        return Response(status=status.HTTP_200_OK, data=serializer.data)

    def post(self, request):
        serializer = serializers.OrderCreateSerializer(
            data=request.data, context={"request": request}
        )
        if serializer.is_valid():
            order = serializer.save(user=request.user)
            return Response(
                serializers.OrderSerializer(order).data, status=status.HTTP_201_CREATED
            )
        return Response(status=status.HTTP_400_BAD_REQUEST, data=serializer.errors)


class OrderItemAPIView(APIView):
    serializer_class = serializers.OrderItemSerializer

    def get(self, request, order_id):
        order = get_object_or_404(Order, id=order_id, user=request.user)
        items = order.items.all()
        serializer = self.serializer_class(items, many=True)
        return Response(status=status.HTTP_200_OK, data=serializer.data)


class ProductAPIView(APIView):
    serializer_class = serializers.ProductSerializer

    def get(self, request, product_id=None):
        if product_id:
            product = get_object_or_404(Product, id=product_id)
            serializer = self.serializer_class(product)
            return Response(status=status.HTTP_200_OK, data=serializer.data)

        cache_key = "priduct_list"
        product_data = cache.get(cache_key)

        if product_data is None:
            products = Product.objects.filter(is_active=True)
            serializer = serializers.ProductSerializer(products, many=True)
            product_data = serializer.data
            cache.set(cache_key, product_data, timeout=300)

        return Response(status=status.HTTP_200_OK, data=product_data)

    def post(self, request):
        serializer = serializers.ProductSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(status=status.HTTP_201_CREATED, data=serializer.data)
        return Response(status=status.HTTP_400_BAD_REQUEST, data=serializer.errors)


@api_view(["POST"])
@permission_classes([AllowAny])
def payment_webhook(request):
    data = request.data

    event_id = data.get("event_id", str(uuid.uuid4()))
    payment_reference = data.get("reference")
    payment_status = data.get("status")
    amount = data.get("amount")

    if not all([payment_reference, payment_status, amount]):
        return Response(
            {"error": "Missing required fields"}, status=status.HTTP_400_BAD_REQUEST
        )

    process_payment_webhook.delay(event_id, payment_reference, payment_status, amount)

    return Response({"message": "Webhook received"}, status=status.HTTP_200_OK)
