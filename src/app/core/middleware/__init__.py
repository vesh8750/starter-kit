"""HTTP middleware.

Written as raw ASGI middleware rather than Starlette's ``BaseHTTPMiddleware``, which
wraps every request in an extra task and has long-standing interactions with streaming
responses, background tasks and exception propagation.

Installation order is defined in :func:`app.core.middleware.setup.install_middleware`
and it matters -- see the comments there.
"""
