"""Outbound integrations with third-party services.

One subclass of :class:`~app.integrations.http.ServiceClient` per external service,
living in its own module here. Feature modules depend on that client, not on ``httpx``,
so retries, timeouts, error translation and logging are solved once and an integration
can be faked in tests by overriding a single dependency.
"""
