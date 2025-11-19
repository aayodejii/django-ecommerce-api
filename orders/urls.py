from django.urls import path

from orders.views import ProductAPIView, OrderAPIView, payment_webhook


urlpatterns = [
    path("", OrderAPIView.as_view(), name="create-orders"),
    path("<uuid:order_id>/", OrderAPIView.as_view(), name="order-detail"),
    path("products/", ProductAPIView.as_view(), name="create-products"),
    path("products/<uuid:product_id>/", ProductAPIView.as_view(), name="get-product"),
    path("webhooks/payment/", payment_webhook, name="get-product"),
]
