from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from django_ratelimit.exceptions import Ratelimited


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if isinstance(exc, Ratelimited):
        return Response(
            {"detail": "Rate limit exceeded. Please try again later."},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    return response
