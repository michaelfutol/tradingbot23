import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dotenv import dotenv_values
from bot import setup_wizard


class PaperSetupTests(unittest.TestCase):
    def test_okx_paper_config_does_not_require_binance_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            with patch.object(setup_wizard, "_get_env_path", return_value=path):
                self.assertTrue(setup_wizard._needs_setup())
                setup_wizard._write_env({"capital": "100.50"})
                self.assertFalse(setup_wizard._needs_setup())
                data = dotenv_values(path)
                self.assertEqual(data["CAPITAL_USD"], "100.5")
                self.assertEqual(data["FUTURES_EXCHANGE"], "okx")
                self.assertEqual(data["AUTO_START_FUTURES"], "false")
                self.assertEqual(data["BINANCE_API_KEY"], "")

    def test_invalid_capital_is_not_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            with patch.object(setup_wizard, "_get_env_path", return_value=path):
                for capital in ("nan", "inf", "0", "-1", "text"):
                    with self.assertRaises(ValueError):
                        setup_wizard._write_env({"capital": capital})
                self.assertFalse(path.exists())

    def test_cancelling_gui_does_not_prompt_for_terminal_credentials(self):
        with patch.object(setup_wizard, "_needs_setup", return_value=True), \
             patch.object(setup_wizard, "run_gui_wizard", return_value=False), \
             patch.object(setup_wizard, "run_terminal_wizard") as terminal:
            self.assertFalse(setup_wizard.ensure_setup())
            terminal.assert_not_called()
