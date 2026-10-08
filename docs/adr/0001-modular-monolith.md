# ADR 0001: Modular monolith

Qadam Media remains one deployable backend with explicit API, service, domain,
integration and worker boundaries. This keeps transactions local while allowing
the worker role to scale independently from the HTTP role.
