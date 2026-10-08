# ADR 0006: Versioned HTTP API

Product endpoints live below `/api/v1`. Health and OAuth callback endpoints keep
stable unversioned paths because they are consumed by infrastructure and an
external provider rather than the web application alone.
