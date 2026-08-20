# SPDX-License-Identifier: GPL-3.0-or-later
"""`mcmt` 的進入點。只解析參數、呼叫、印結果。

離開碼：0 一切正常 · 1 世界被拒絕處理 · 2 使用者的輸入有問題。
"""

import argparse
import sys

from mcmt.cli.apply import format_apply, run_apply
from mcmt.cli.doctor import format_survey
from mcmt.cli.extract import format_result, run_extract
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

    extract = sub.add_parser(
        "extract", help="掃描世界，產出待翻檔（唯讀掃描，只寫 sandbox）"
    )
    extract.add_argument("world", help="世界資料夾路徑")
    extract.add_argument("--lang", default="zh_tw", help="目標語言，預設 zh_tw")
    extract.add_argument("--namespace", default="mcmt", help="lang key 命名空間")
    extract.add_argument("--out", default=None, help="產出目錄，預設 sandbox/.mcmt-out/<世界名>")
    extract.add_argument(
        "--replace", action="store_true", help="覆蓋既有的待翻檔（會蓋掉已填的譯文）"
    )

    apply = sub.add_parser("apply", help="讀翻好的檔案，產出資源包並寫回世界")
    apply.add_argument("world", help="世界資料夾（必須在 sandbox 底下）")
    apply.add_argument(
        "--translations", required=True, help="翻好的 translations.<lang>.json"
    )
    apply.add_argument("--extract", default=None, help="對應的 extract.json，預設同目錄")
    apply.add_argument(
        "--dry-run", action="store_true", help="完全不碰存檔，只印出打算改什麼"
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

    if args.command == "extract":
        try:
            summary = run_extract(
                args.world,
                language=args.lang,
                namespace=args.namespace,
                out=args.out,
                replace=args.replace,
            )
        except FileExistsError as exc:
            print(
                f"mcmt: {exc} 已經存在。要覆蓋請加 --replace"
                f"（那會蓋掉你已經填進去的譯文）。",
                file=sys.stderr,
            )
            return 2
        except (WorldNotFoundError, SafetyError, FileNotFoundError, OSError) as exc:
            return _user_error(exc)
        print(format_result(summary))
        return 0

    if args.command == "apply":
        try:
            summary = run_apply(
                args.world,
                args.translations,
                extract_path=args.extract,
                dry_run=args.dry_run,
            )
        except (WorldNotFoundError, SafetyError, FileNotFoundError, ValueError) as exc:
            return _user_error(exc)
        print(format_apply(summary))
        return 0

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
