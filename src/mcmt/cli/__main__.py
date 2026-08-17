# SPDX-License-Identifier: GPL-3.0-or-later
"""`mcmt` 的進入點。只解析參數、呼叫、印結果。

離開碼：0 一切正常 · 1 世界被拒絕處理 · 2 使用者的輸入有問題。
"""

import argparse
import sys

from mcmt.cli.doctor import format_survey
from mcmt.cli.sandbox import format_import
from mcmt.doctor import survey_world
from mcmt.errors import SafetyError, WorldNotFoundError
from mcmt.sandbox import import_world


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mcmt", description="Minecraft 地圖翻譯工具")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="健檢一個世界（唯讀）")
    doctor.add_argument("world", help="世界資料夾路徑")

    sandbox = sub.add_parser("sandbox", help="sandbox 管理")
    sandbox_sub = sandbox.add_subparsers(dest="sandbox_command", required=True)
    importer = sandbox_sub.add_parser(
        "import", help="把一個世界完整複製進 sandbox（唯一合法的入口）"
    )
    importer.add_argument("source", help="來源世界資料夾")
    importer.add_argument("--name", help="sandbox 裡的名字，預設沿用來源資料夾名")
    importer.add_argument(
        "--replace", action="store_true", help="目標已存在時覆蓋（會刪掉整份現有副本）"
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "doctor":
        try:
            survey = survey_world(args.world)
        except WorldNotFoundError as exc:
            return _user_error(exc)
        print(format_survey(survey))
        return 0 if survey.supported else 1

    if args.command == "sandbox" and args.sandbox_command == "import":
        try:
            result = import_world(args.source, name=args.name, replace=args.replace)
        except (WorldNotFoundError, SafetyError) as exc:
            return _user_error(exc)
        print(format_import(result))
        return 0

    raise AssertionError(f"未處理的子命令：{args.command}")  # pragma: no cover


def _user_error(exc: Exception) -> int:
    print(f"mcmt: {exc}", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
