class DomainError(ValueError):
    """A safe, expected violation of a business rule."""

    code = "domain_error"


class ConflictError(DomainError):
    code = "conflict"


class RuleViolation(DomainError):
    code = "rule_violation"
