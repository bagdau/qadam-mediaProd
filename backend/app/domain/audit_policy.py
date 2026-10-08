SENSITIVE_KEYS = frozenset({"access_token", "refresh_token", "client_secret", "password", "upload_url"})


def sanitize_audit_details(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in SENSITIVE_KEYS else sanitize_audit_details(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_audit_details(item) for item in value]
    return value
