"""Short-circuit matched model calls with locally generated replies.

Registered after ``ModelInterceptorAddon`` so that addon has already authorized the
call, stamped ``flow.metadata`` and emitted ``llm_request``. Setting ``flow.response``
here stops mitmproxy from opening any upstream connection while still triggering the
main addon's ``response`` hook, so the ``llm_request``/``llm_response`` trace pair
closes exactly as it does for a real provider.
"""

from __future__ import annotations

from mitmproxy import http

from .config import Route, ServiceConfig
from .offline import OfflineResponseError, OfflineMockTarget


class OfflineResponderAddon:
    def __init__(self, config: ServiceConfig, target: OfflineMockTarget) -> None:
        self.config = config
        self.target = target
        self.routes = {item.route_id: item for item in config.routes}

    def request(self, flow: http.HTTPFlow) -> None:
        route = self._route(flow)
        if route is None or flow.response is not None:
            return
        try:
            reply = self.target.build_response(
                flow.request.content or b"",
                route=route,
                target=self.config.target,
            )
        except OfflineResponseError as exc:
            flow.response = http.Response.make(
                422,
                str(exc).encode("utf-8"),
                {"Content-Type": "text/plain; charset=utf-8"},
            )
            return
        flow.response = http.Response.make(
            reply.status,
            reply.content,
            dict(reply.headers),
        )

    def _route(self, flow: http.HTTPFlow) -> Route | None:
        """Only answer flows the main addon already matched and authorized."""

        route_id = flow.metadata.get("defuzex_route")
        if not isinstance(route_id, str):
            return None
        return self.routes.get(route_id)
