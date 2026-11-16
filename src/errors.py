"""Errors that carry an HTTP status.

The API answers with a JSON body and a status code rather than an HTML error
page, so a failure inside a route raises one of these and the app's error
handler turns it into the right response.
"""

from werkzeug.exceptions import HTTPException


class ApiError(Exception):
    """An error with a message and a status code.

    `payload` carries any extra keys the route's response shape needs, so a
    route can raise and still answer in its own format.
    """

    status = 500

    def __init__(self, message, status=None, **payload):
        super().__init__(message)
        self.message = message
        if status is not None:
            self.status = status
        self.payload = payload


class ChatError(ApiError):
    """Raised inside the chat pipeline, which has its own response shape."""


def is_http_exception(exc):
    return isinstance(exc, HTTPException)
