class AppError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class AgentUnavailable(AppError):
    """The app could not determine the outcome of an agent request."""


class AgentRejected(AppError):
    def __init__(self, message: str, aborted_run: str | None = None) -> None:
        super().__init__(message, 502)
        self.aborted_run = aborted_run
