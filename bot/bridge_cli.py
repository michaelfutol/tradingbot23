"""LUM/Desktop Commander client; never starts a second portfolio writer."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

import requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "history", "p2p", "pause", "resume", "run-once", "operation"])
    parser.add_argument("--access-file", required=True, type=Path)
    parser.add_argument("--id", help="Operation ID to inspect")
    args = parser.parse_args()
    try:
        access = json.loads(args.access_file.read_text(encoding="utf-8"))
        url = urlparse(access["url"])
        if url.scheme != "http" or url.hostname != "127.0.0.1" or url.path or url.query or url.username:
            raise ValueError("Bridge URL must be loopback-only")
        session = requests.Session()
        session.trust_env = False
        headers = {"Authorization": "Bearer " + access["token"]}
        if args.action in {"pause", "resume", "run-once"}:
            response = session.post(access["url"] + "/commands", json={"action": args.action},
                                    headers=headers, timeout=5, allow_redirects=False)
        else:
            path = "/" + args.action
            if args.action == "operation":
                if not args.id or not all(c in "0123456789abcdef" for c in args.id) or len(args.id) != 24:
                    raise ValueError("A valid operation ID is required")
                path = "/operations/" + args.id
            response = session.get(access["url"] + path, headers=headers, timeout=5, allow_redirects=False)
        response.raise_for_status()
        print(json.dumps(response.json(), indent=2, allow_nan=False))
    except (OSError, ValueError, KeyError, requests.RequestException):
        parser.exit(1, "Bridge unavailable or request rejected. Open TradingBot23 and check the private access-file path.\n")


if __name__ == "__main__":
    main()
