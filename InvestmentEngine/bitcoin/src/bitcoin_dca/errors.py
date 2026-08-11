"""Domain-specific errors for the local Smart DCA runtime."""


class BitcoinDcaError(Exception):
    """Base class for expected runtime errors."""


class ConfigError(BitcoinDcaError):
    """The versioned machine configuration is missing or invalid."""


class JournalValidationError(BitcoinDcaError):
    """Canonical Journal data violates its schema or invariants."""

    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("; ".join(issues))


class LockUnavailableError(BitcoinDcaError):
    """Another process currently owns the Journal lock."""


class UserInputError(BitcoinDcaError):
    """A requested operation contains invalid user input."""


class OperationCancelled(BitcoinDcaError):
    """The operator declined an interactive write confirmation."""

