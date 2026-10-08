import hashlib
import hmac


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    supplied = signature.removeprefix("sha256=").lower()
    return hmac.compare_digest(expected, supplied)
