"""Errors the core needs to reason about, independent of any backend or transport."""


class AmbiguousWriteError(Exception):
    """A write to a backend timed out or failed mid-flight; it may or may not have been applied.

    The caller must check the backend (by its idempotency key) before repeating the write.
    """

    def __init__(self, target: str, cause: Exception):
        super().__init__(f"Write to {target} has unknown outcome: {cause}")
        self.url = target
        self.cause = cause
