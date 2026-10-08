REQUIRED_LOGIN_SCOPES = frozenset({"user.info.basic"})
PUBLISH_SCOPE = "video.publish"
UPLOAD_SCOPE = "video.upload"


def missing_scopes(granted: list[str], required: set[str] | frozenset[str]) -> set[str]:
    return set(required) - {scope.strip() for scope in granted}
