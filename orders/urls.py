from django.urls import path

from orders.views import ProductAPIView, OrderAPIView


urlpatterns = [
    path("", OrderAPIView.as_view(), name="create-orders"),
    path("products/", ProductAPIView.as_view(), name="create-products"),
    path("products/<uuid:product_id>/", ProductAPIView.as_view(), name="get-product"),
]
