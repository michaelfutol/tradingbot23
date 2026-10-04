import unittest
from unittest.mock import patch
from pathlib import Path
from PIL import Image

from bot.dashboard import Dashboard
from bot import ui_theme


class Trade23PresentationTests(unittest.TestCase):
    def test_small_prices_do_not_disappear_at_four_decimals(self):
        self.assertEqual(Dashboard._price_text(0.00000812), "$0.00000812")
        self.assertEqual(Dashboard._price_text(76000.25), "$76,000.2500")
        self.assertEqual(Dashboard._price_text(None), "--")
        self.assertEqual(Dashboard._price_text(float("nan")), "--")

    def test_brand_assets_have_native_window_sizes(self):
        for size in (32, 40, 64, 256):
            with Image.open(ui_theme.asset_path(f"ui/mark-{size}.png")) as img:
                self.assertEqual(img.size, (size, size))

    def test_frozen_asset_lookup_uses_packaged_resources_not_user_data(self):
        with patch.object(ui_theme.sys, "_MEIPASS", "bundle", create=True):
            self.assertEqual(ui_theme.asset_path("ui/mark-32.png"), Path("bundle/assets/ui/mark-32.png"))
