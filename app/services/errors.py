class LifeHelperError(Exception):
    """Base application service error."""


class ListNotFound(LifeHelperError):
    """Shopping list does not exist."""


class AccessDenied(LifeHelperError):
    """User has no rights for the requested action."""


class ValidationError(LifeHelperError):
    """User-provided data is invalid."""
