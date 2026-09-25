"""Explicit Stage M ASGI composition; the generic/Stage L entrypoint is unchanged."""
from ai_bridge.api.app import create_app
from ai_bridge.domains.ers.adapter import ERSAdapter
from ai_bridge.domains.wvc.adapter import WVCAdapter
from .adapter import CRTAdapter
from ai_bridge.providers.platform_api import PlatformAPIProvider
from ai_bridge.settings import get_settings


def create_stage_m_app(settings=None, *, provider=None):
    settings = settings if settings is not None else get_settings()
    provider = provider if provider is not None else PlatformAPIProvider(settings)
    return create_app(settings, domains=(WVCAdapter(), ERSAdapter(), CRTAdapter(provider)))


app = create_stage_m_app()
