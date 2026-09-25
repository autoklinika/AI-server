from __future__ import annotations

import logging
import sys
from pathlib import Path

import uvicorn

from .settings import get_settings


def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    stage_m = (
        Path(__file__).with_name("stage_m_enabled").is_file()
        or (Path(sys.prefix).parent / "src/ai_bridge/stage_m_enabled").is_file()
    )
    uvicorn.run(
        "ai_bridge.domains.crt.release:app" if stage_m else "ai_bridge.api.app:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=False,
    )


if __name__ == "__main__":
    main()
