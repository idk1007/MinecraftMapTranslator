# SPDX-License-Identifier: GPL-3.0-or-later
"""`mcmt` 的進入點。只解析參數、呼叫、印結果。

離開碼：0 一切正常 · 1 世界被拒絕處理 · 2 使用者的輸入有問題。
"""

import argparse
import sys

from mcmt.cli.doctor import format_survey
from mcmt.doctor import survey_world
from mcmt.errors import WorldNotFoundError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mcmt", description="Minecraft 地圖翻譯工具")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="健檢一個世界（唯讀）")
    doctor.add_argument("world", help="世界資料夾路徑")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "doctor":
        try:
            survey = survey_world(args.world)
        except WorldNotFoundError as exc:
            print(f"mcmt: {exc}", file=sys.stderr)
            return 2
        print(format_survey(survey))
        return 0 if survey.supported else 1

    raise AssertionError(f"未處理的子命令：{args.command}")  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
