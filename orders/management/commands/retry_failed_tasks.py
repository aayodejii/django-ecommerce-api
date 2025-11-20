from django.core.management.base import BaseCommand
from orders.models import FailedTask
from django.utils import timezone
from celery import current_app


class Command(BaseCommand):
    help = "Retry failed tasks from dead letter queue"

    def add_arguments(self, parser):
        parser.add_argument("--task-id", type=str, help="Specific task ID to retry")
        parser.add_argument(
            "--all", action="store_true", help="Retry all unretried tasks"
        )

    def handle(self, *args, **options):
        if options["task_id"]:
            try:
                failed_task = FailedTask.objects.get(task_id=options["task_id"])
                self.retry_task(failed_task)
            except FailedTask.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f"Task {options['task_id']} not found")
                )

        elif options["all"]:
            failed_tasks = FailedTask.objects.filter(retried=False)
            count = failed_tasks.count()

            for failed_task in failed_tasks:
                self.retry_task(failed_task)

            self.stdout.write(self.style.SUCCESS(f"Retried {count} tasks"))

        else:
            self.stdout.write(self.style.WARNING("Use --task-id or --all"))

    def retry_task(self, failed_task):
        task = current_app.tasks.get(failed_task.task_name)

        if task:
            task.apply_async(args=failed_task.args, kwargs=failed_task.kwargs)

            failed_task.retried = True
            failed_task.retried_at = timezone.now()
            failed_task.save()

            self.stdout.write(self.style.SUCCESS(f"Retried task {failed_task.task_id}"))
        else:
            self.stdout.write(
                self.style.ERROR(f"Task {failed_task.task_name} not found in registry")
            )
