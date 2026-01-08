"""Custom exceptions for the copy bot."""


class BotError(Exception):
    """Base exception for bot errors."""
    pass


class ConfigError(BotError):
    """Configuration error."""
    pass


class ConnectionError(BotError):
    """Connection error to external services."""
    pass


class ExecutionError(BotError):
    """Trade execution error."""
    pass


class ValidationError(BotError):
    """Validation error."""
    pass
