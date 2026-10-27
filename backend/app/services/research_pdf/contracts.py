"""Small shared contracts for the resource-scoped PDF export workflow."""

class PdfExportError(ValueError):
    """An actionable error safe to return to the export UI."""

    def __init__(self, code, message, *, retryable=False, details=None):
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.retryable = bool(retryable)
        self.details = details or {}

    def public(self):
        return {"code": self.code, "message": self.message, "retryable": self.retryable}
