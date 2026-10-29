class PipelineValidationError(ValueError):
    """Validation failure carrying findings not yet returned to the caller."""

    def __init__(self, message, issues=None):
        super().__init__(message)
        self.issues = list(issues or [])
