"""Compatibility import; implementation belongs to the WVC domain."""
import sys
from importlib import import_module

sys.modules[__name__] = import_module("ai_bridge.domains.wvc.profiles.analysis_profile")
