from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from src.exporter import run_export
from src.models import ExportOptions
from src.utils import OUTPUTS_DIR, helsinki_today

DEFAULT_PROXY_HOST = "127.0.0.1"
DEFAULT_PROXY_PORT = 11808
DEFAULT_MODE = "public_web"


def build_proxy(use_proxy: bool, host: str, port: int) -> dict[str, str] | None:
    if not use_proxy:
        return None
    url = f"socks5h://{host}:{port}"
    return {"http": url, "https": url}


def parse_sources(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}, expected YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="daily_export.py",
        description="Headless public_web export (one day) reusing the project export logic.",
    )
    parser.add_argument(
        "--sources",
        required=True,
        help="Comma-separated Telegram sources, e.g. '@channel_a,@channel_b'",
    )
    parser.add_argument(
        "--date",
        type=parse_date,
        default=None,
        help="Export date as YYYY-MM-DD (default: today in Europe/Helsinki)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUTS_DIR,
        help=f"Outputs root (default: {OUTPUTS_DIR})",
    )
    parser.add_argument(
        "--proxy-host",
        default=DEFAULT_PROXY_HOST,
        help=f"SOCKS5 host (default: {DEFAULT_PROXY_HOST})",
    )
    parser.add_argument(
        "--proxy-port",
        type=int,
        default=DEFAULT_PROXY_PORT,
        help=f"SOCKS5 port (default: {DEFAULT_PROXY_PORT})",
    )
    parser.add_argument(
        "--no-proxy",
        action="store_true",
        help="Disable SOCKS5 proxy and use the current public_web behaviour",
    )
    return parser


def _configure_logging() -> None:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def _emit(summary: dict[str, object]) -> None:
    print(json.dumps(summary, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging()

    sources = parse_sources(args.sources)
    day = args.date or helsinki_today()
    proxy = build_proxy(not args.no_proxy, args.proxy_host, args.proxy_port)

    if not sources:
        _emit(
            {
                "date": str(day),
                "sources": 0,
                "OK": 0,
                "NO_MESSAGES": 0,
                "ERROR": 0,
                "SKIPPED_EXISTING_COMPLETE": 0,
                "manifest": "",
                "run_report": "",
                "proxy": proxy["https"] if proxy else None,
                "error": "no sources provided",
            }
        )
        return 2

    options = ExportOptions(
        mode=DEFAULT_MODE,
        sources=sources,
        start_date=day,
        end_date=day,
        proxy=proxy,
    )

    try:
        artifacts, results = run_export(options, outputs_root=args.output_dir)
    except Exception as exc:
        logging.exception("Headless export failed")
        _emit(
            {
                "date": str(day),
                "sources": len(sources),
                "OK": 0,
                "NO_MESSAGES": 0,
                "ERROR": len(sources),
                "SKIPPED_EXISTING_COMPLETE": 0,
                "manifest": "",
                "run_report": "",
                "proxy": proxy["https"] if proxy else None,
                "error": str(exc),
            }
        )
        return 1

    counts = Counter(result.status for result in results)
    _emit(
        {
            "date": str(day),
            "sources": len(sources),
            "OK": counts["OK"],
            "NO_MESSAGES": counts["NO_MESSAGES"],
            "ERROR": counts["ERROR"],
            "SKIPPED_EXISTING_COMPLETE": counts["SKIPPED_EXISTING_COMPLETE"],
            "manifest": str(artifacts.manifest_path),
            "run_report": str(artifacts.run_path),
            "proxy": proxy["https"] if proxy else None,
        }
    )
    return 0 if counts["ERROR"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())