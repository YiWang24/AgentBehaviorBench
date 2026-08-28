"""mitmproxy script loader using the mounted service configuration."""

from __future__ import annotations

import os

from defuzex_model_interceptor.addon import ModelInterceptorAddon
from defuzex_model_interceptor.config import ServiceConfig
from defuzex_model_interceptor.entrypoint import CONFIG_ENV, DEFAULT_CONFIG
from defuzex_model_interceptor.offline import OFFLINE_TARGET_PLUGIN
from defuzex_model_interceptor.offline_addon import OfflineResponderAddon
from defuzex_model_interceptor.registry import load_targets


_config = ServiceConfig.load(os.environ.get(CONFIG_ENV, DEFAULT_CONFIG))

addons = [ModelInterceptorAddon(_config)]

# Order matters: the responder must run after the main addon has authorized the
# call and emitted llm_request, otherwise the trace pair would never open.
if _config.target.target_plugin == OFFLINE_TARGET_PLUGIN:
    addons.append(
        OfflineResponderAddon(_config, load_targets()[OFFLINE_TARGET_PLUGIN])
    )
