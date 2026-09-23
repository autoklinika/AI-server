"""Compatibility CLI; WVC policy lives in its domain adapter."""
import sys
from ai_bridge.domains.wvc.analysis import main as implementation

if __name__ == "__main__":
    raise SystemExit(implementation.main())
sys.modules[__name__] = implementation
