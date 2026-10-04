"""Shared test helpers."""

import tempfile
from pathlib import Path

from bot import config


def isolate_data_dir(testcase):
    """Run a test with an empty temporary DATA_DIR."""
    previous = config.DATA_DIR
    settings = {name: value for name, value in vars(config).items() if name.isupper()}
    tmp = tempfile.TemporaryDirectory()
    config.DATA_DIR = Path(tmp.name)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)

    def cleanup():
        for name, value in settings.items():
            setattr(config, name, value)
        config.DATA_DIR = previous
        tmp.cleanup()

    testcase.addCleanup(cleanup)
    config.TELEGRAM_BOT_TOKEN = ""
    config.TELEGRAM_CHAT_ID = ""
    config.OHVERLAY_ENABLED = False
    return config.DATA_DIR
