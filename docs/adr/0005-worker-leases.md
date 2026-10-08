# ADR 0005: Worker leases

Workers claim publication work with an expiring database lease. An expired lease
after a non-idempotent TikTok call moves work to manual review instead of blindly
repeating the call and risking a duplicate post.
