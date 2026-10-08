# ADR 0002: Server-owned secrets

Browser code never receives TikTok client secrets, access tokens or upload URLs.
Opaque credentials are encrypted at rest and only decrypted inside the backend or
worker immediately before an upstream request.
