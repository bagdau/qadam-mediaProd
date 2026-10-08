import re

MENTION = re.compile(r"(?<!\w)@[A-Za-z0-9._]{2,24}")
HASHTAG = re.compile(r"(?<!\w)#[\w]{1,100}", re.UNICODE)


def caption_entities(value: str) -> dict[str, list[str]]:
    return {"mentions": MENTION.findall(value), "hashtags": HASHTAG.findall(value)}
