from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


class AccountStatus(StrEnum):
    ACTIVE = "active"
    NEEDS_REAUTH = "needs_reauth"
    REVOKED = "revoked"


class PublicationMode(StrEnum):
    DIRECT_POST = "DIRECT_POST"
    UPLOAD_TO_INBOX = "UPLOAD_TO_INBOX"


class PublicationStatus(StrEnum):
    QUEUED = "QUEUED"
    INITIATING = "INITIATING"
    UPLOADING = "UPLOADING"
    PROCESSING = "PROCESSING"
    PUBLISHED = "PUBLISHED"
    INBOX_DELIVERED = "INBOX_DELIVERED"
    FAILED = "FAILED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    CANCELLED = "CANCELLED"


TERMINAL_STATUSES = frozenset(
    {
        PublicationStatus.PUBLISHED,
        PublicationStatus.INBOX_DELIVERED,
        PublicationStatus.FAILED,
        PublicationStatus.NEEDS_REVIEW,
        PublicationStatus.CANCELLED,
    }
)
ACTIVE_STATUSES = frozenset(set(PublicationStatus) - TERMINAL_STATUSES)

PRIVACY_LEVELS = (
    "PUBLIC_TO_EVERYONE",
    "MUTUAL_FOLLOW_FRIENDS",
    "FOLLOWER_OF_CREATOR",
    "SELF_ONLY",
)


def sql_in(values) -> str:
    return ", ".join(f"'{getattr(v, 'value', v)}'" for v in values)
