"""Read-only legacy deposit audit. Monthly cash injection has been retired."""

import json

from bot import config


def load_account_state() -> dict:
    path = config.DATA_DIR / "account_state.json"
    if not path.exists():
        return {"total_contributed_usd": 0.0, "contributions": []}
    # A corrupt ledger must not silently erase deposits.
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid legacy deposit audit")
    data.setdefault("total_contributed_usd", 0.0)
    data.setdefault("contributions", [])
    return data


def total_contributed_capital() -> float:
    """Legacy account baseline, used only to migrate old saved accounts."""
    return config.CAPITAL_USD + float(load_account_state()["total_contributed_usd"])
