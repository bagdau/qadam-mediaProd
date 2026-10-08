SUCCESS_STATUSES = frozenset({"PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"})
FAILURE_STATUS = "FAILED"
PENDING_STATUSES = frozenset({"PROCESSING_UPLOAD", "PROCESSING_DOWNLOAD", "PUBLISHING"})


def classify_publish_status(status: str) -> str:
    if status in SUCCESS_STATUSES:
        return "success"
    if status == FAILURE_STATUS:
        return "failure"
    if status in PENDING_STATUSES:
        return "pending"
    return "unknown"
