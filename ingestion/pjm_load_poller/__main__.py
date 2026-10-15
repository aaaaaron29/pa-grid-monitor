"""Entry point: python -m ingestion.pjm_load_poller"""
from __future__ import annotations

from common.config import get_settings
from common.logging import configure_logging
from common.metrics import start_metrics_server
from ingestion.pjm_load_poller.poller import run_forever


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    start_metrics_server(settings.metrics_port)
    run_forever(settings)


if __name__ == "__main__":
    main()
