"""Errors raised by the services. Each carries the HTTP status returned for it."""


class ServiceError(Exception):
    """A request the services refused. `message` is returned to the caller as-is."""

    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class RejectedError(ServiceError):
    """Bad input or a business rule: unknown ticker, insufficient cash or shares, duplicate."""

    status_code = 400


class NotFoundError(ServiceError):
    """The requested item does not exist."""

    status_code = 404


class PriceUnavailableError(ServiceError):
    """The ticker has no price yet, so it cannot be traded."""

    status_code = 503
