class UnsupportedSchemaVersion(ValueError):
    def __init__(self, received: int, supported: tuple[int, ...] = (1,)) -> None:
        self.received = received
        self.supported = supported
        super().__init__(f"Unsupported schema version {received}")


class BatchIdentityConflict(RuntimeError):
    """The same source_id/batch_id was reused for different content."""
