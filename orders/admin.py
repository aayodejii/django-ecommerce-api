from django.contrib import admin

from orders.models import (
    Product,
    Order,
    OrderItem,
    WebhookEvent,
    EmailLog,
    DailySalesReport,
    LowStockAlert,
    WebhookCleanupLog,
    FailedTask,
)

admin.site.register(Order)
admin.site.register(OrderItem)
admin.site.register(Product)
admin.site.register(EmailLog)
admin.site.register(WebhookEvent)


@admin.register(DailySalesReport)
class DailySalesReportAdmin(admin.ModelAdmin):
    list_display = ["date", "total_orders", "total_revenue", "status", "generated_at"]
    list_filter = ["status", "date"]
    readonly_fields = [
        "date",
        "total_orders",
        "total_revenue",
        "generated_at",
        "created_at",
        "updated_at",
    ]

    def has_add_permission(self, request):
        return False


@admin.register(LowStockAlert)
class LowStockAlertAdmin(admin.ModelAdmin):
    list_display = ["product", "stock_level", "alert_sent", "sent_at", "created_at"]
    list_filter = ["alert_sent", "created_at"]
    readonly_fields = ["product", "stock_level", "sent_at", "created_at"]

    def has_add_permission(self, request):
        return False


@admin.register(WebhookCleanupLog)
class WebhookCleanupLogAdmin(admin.ModelAdmin):
    list_display = [
        "run_date",
        "archived_count",
        "deleted_count",
        "status",
        "created_at",
    ]
    list_filter = ["status", "run_date"]
    readonly_fields = [
        "run_date",
        "archived_count",
        "deleted_count",
        "status",
        "created_at",
    ]

    def has_add_permission(self, request):
        return False


@admin.register(FailedTask)
class FailedTaskAdmin(admin.ModelAdmin):
    list_display = ["task_name", "task_id", "failed_at", "retried"]
    list_filter = ["task_name", "retried", "failed_at"]
    search_fields = ["task_id", "exception"]
    readonly_fields = [
        "task_name",
        "task_id",
        "args",
        "kwargs",
        "exception",
        "traceback",
        "failed_at",
    ]

    def has_add_permission(self, request):
        return False
