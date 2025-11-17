from rest_framework.views import APIView, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from django.shortcuts import get_object_or_404

from orders import serializers
from orders.models import Order, OrderItem, Product


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
        products = Product.objects.all()
        serializer = serializers.ProductSerializer(products, many=True)
        return Response(status=status.HTTP_200_OK, data=serializer.data)

    def post(self, request):
        serializer = serializers.ProductSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(status=status.HTTP_201_CREATED, data=serializer.data)
        return Response(status=status.HTTP_400_BAD_REQUEST, data=serializer.errors)
