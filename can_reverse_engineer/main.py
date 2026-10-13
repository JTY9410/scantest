"""CAN/UDS/BMS 역분석 도구 진입점.

    python main.py inventory ./dataset/inbox          # REQ-01
    python -m can_reverse_engineer.main inventory …   # 저장소 루트에서
"""

import argparse
import logging
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from can_reverse_engineer.parsers.inventory import build_inventory  # noqa: E402
from can_reverse_engineer.reports.inventory_report import write_outputs  # noqa: E402

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "output"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CAN/UDS/BMS Reverse Engineering")
    commands = parser.add_subparsers(dest="command", required=True)
    inventory = commands.add_parser("inventory", help="REQ-01 입력 데이터 Inventory")
    inventory.add_argument("input_dir", type=Path)
    inventory.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    inventory.add_argument("--sample-size", type=int, default=50, help="TRC 앞부분 메시지 수(30~50)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not args.input_dir.is_dir():
        parser.error(f"입력 디렉터리가 없습니다: {args.input_dir}")
    result = build_inventory(args.input_dir, args.sample_size)
    for path in write_outputs(result, args.output):
        logging.info("저장: %s", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
