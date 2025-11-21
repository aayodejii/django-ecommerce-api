from prometheus_client import Counter, Histogram, Gauge

orders_created_total = Counter(
    "orders_created_total", "Total number of orders created", ["status"]
)

order_value_total = Counter(
    "order_value_total", "Total value of all orders in Naira", ["payment_status"]
)

order_creation_duration = Histogram(
    "order_creation_duration_seconds",
    "Time taken to create an order",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

payment_webhook_processed_total = Counter(
    "payment_webhook_processed_total", "Total payment webhooks processed", ["status"]
)

celery_task_duration = Histogram(
    "celery_task_duration_seconds",
    "Celery task execution time",
    ["task_name"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

celery_task_total = Counter(
    "celery_task_total", "Total Celery tasks executed", ["task_name", "status"]
)

active_orders_gauge = Gauge("active_orders_total", "Current number of pending orders")

low_stock_products_gauge = Gauge(
    "low_stock_products_total", "Current number of low stock products"
)

redis_lock_acquisitions = Counter(
    "redis_lock_acquisitions_total", "Total Redis lock acquisitions", ["status"]
)

stock_quantity_gauge = Gauge(
    "product_stock_quantity",
    "Current stock quantity per product",
    ["product_id", "product_name"],
)
