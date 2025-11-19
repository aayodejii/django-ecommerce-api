from django.contrib import admin

from orders.models import Order, OrderItem, Product, EmailLog


admin.site.register(Order)
admin.site.register(OrderItem)
admin.site.register(Product)
admin.site.register(EmailLog)
