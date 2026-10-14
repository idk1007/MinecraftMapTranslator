# SPDX-License-Identifier: GPL-3.0-or-later
"""`mcmt` 的進入點。只解析參數、呼叫、印結果。

離開碼：0 一切正常 · 1 世界被拒絕處理 · 2 使用者的輸入有問題 · 3 工具自己出錯。

**使用者看到的每一則錯誤都是「【標題】＋內容」**（措辭見
`docs/error-messages-review.md`）。沒被預期的例外不印 Python 堆疊：寫進沙盒裡的
`mcmt-error.log`，畫面上只留一句話與日誌位置。
"""

import argparse
import platform
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path

from mcmt.cli.apply import format_apply, run_apply
from mcmt.cli.doctor import format_survey
from mcmt.cli.extract import format_result, run_extract
from mcmt.cli.sandbox import format_import
from mcmt.doctor import survey_world
from mcmt.errors import (
    FileAccessDeniedError,
    McmtError,
    SandboxTargetExistsError,
    TranslationsExistError,
)
from mcmt.safety.paths import ensure_writable, sandbox_root
from mcmt.sandbox import import_world

ERROR_LOG_NAME = "mcmt-error.log"


# argparse 用參數的內部名稱回報缺了誰；換成使用者看得懂的叫法。
_PLAIN_NAMES = {"world": "地圖路徑", "source": "來源地圖路徑"}


class _Parser(argparse.ArgumentParser):
    """argparse 的錯誤訊息是英文，而且不會告訴你範例長什麼樣。"""

    hint: str | None = None

    def error(self, message: str):
        required = re.search(r"required: (.+)$", message)
        if required:
            names = "、".join(
                _PLAIN_NAMES.get(name, name) for name in required.group(1).split(", ")
            )
            lines = [f"【缺少必要選項】", f"未指定 {names}。"]
            if self.hint:
                lines.append(f"格式：{self.hint}")
        else:
            lines = ["【參數有誤】", message]
            if self.hint:
                lines.append(f"格式：{self.hint}")
        self.exit(2, "\n".join(lines) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="mcmt", description="Minecraft 地圖翻譯工具")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="健檢一個世界（唯讀）")
    doctor.hint = 'mcmt doctor "地圖路徑"'
    doctor.add_argument("world", help="世界資料夾路徑")

    sandbox = sub.add_parser("sandbox", help="沙盒（sandbox）管理")
    sandbox_sub = sandbox.add_subparsers(dest="sandbox_command", required=True)
    importer = sandbox_sub.add_parser(
        "import", help="把一個世界完整複製進沙盒（唯一合法的入口）"
    )
    importer.hint = 'mcmt sandbox import "地圖路徑"'
    importer.add_argument("source", help="來源世界資料夾")
    importer.add_argument("--name", help="沙盒裡的名字，預設沿用來源資料夾名")
    importer.add_argument(
        "--replace", action="store_true", help="目標已存在時覆蓋（會刪掉整份現有副本）"
    )

    extract = sub.add_parser(
        "extract", help="掃描世界，產出待翻檔（唯讀掃描，只寫沙盒）"
    )
    extract.hint = 'mcmt extract "沙盒裡的地圖路徑"'
    extract.add_argument("world", help="世界資料夾路徑")
    extract.add_argument("--lang", default="zh_tw", help="目標語言，預設 zh_tw")
    extract.add_argument("--namespace", default="mcmt", help="lang key 命名空間")
    extract.add_argument("--out", default=None, help="產出目錄，預設 sandbox/.mcmt-out/<世界名>")
    extract.add_argument(
        "--replace",
        action="store_true",
        help="覆蓋既有的待翻檔（舊檔會先另存為 .bak-時間）",
    )

    apply = sub.add_parser("apply", help="讀翻好的檔案，產出資源包並寫回世界")
    apply.hint = 'mcmt apply "沙盒裡的地圖路徑" --translations "翻譯檔路徑"'
    apply.add_argument("world", help="世界資料夾（必須在沙盒底下）")
    apply.add_argument(
        "--translations", required=True, help="翻好的 translations.<lang>.json"
    )
    apply.add_argument("--extract", default=None, help="對應的 extract.json，預設同目錄")
    apply.add_argument(
        "--dry-run", action="store_true", help="完全不碰存檔，只印出打算改什麼"
    )

    return parser


def render_error(exc: BaseException) -> str:
    """終端機與對話框共用的格式：【標題】＋內容。"""
    return f"【{getattr(exc, 'title', '發生錯誤')}】\n{exc}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started = datetime.now()
    try:
        return _dispatch(args)
    except KeyboardInterrupt:
        print("已中斷。", file=sys.stderr)
        return 130
    except McmtError as exc:
        print(render_error(exc), file=sys.stderr)
        return 2
    except PermissionError as exc:
        print(render_error(FileAccessDeniedError(exc.filename or "指定的檔案")), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 —— 最後一道網，什麼都接
        return _unexpected(exc, args, started)


def _dispatch(args) -> int:
    if args.command == "doctor":
        survey = survey_world(args.world)
        print(format_survey(survey))
        return 0 if survey.supported else 1

    if args.command == "extract":
        kwargs = dict(
            language=args.lang, namespace=args.namespace, out=args.out
        )
        try:
            summary = run_extract(args.world, replace=args.replace, **kwargs)
        except TranslationsExistError as exc:
            answer = _confirm(
                f"已有 {Path(str(exc.path)).name}，重新抽取會覆蓋它"
                f"（舊檔會先另存為 .bak-時間）。是否覆蓋？"
            )
            if answer is None:
                raise  # 沒有終端機可以問：照原樣報錯，訊息裡有 --replace
            if not answer:
                print("已取消，沒有變更任何檔案。", file=sys.stderr)
                return 2
            summary = run_extract(args.world, replace=True, **kwargs)
        print(format_result(summary))
        return 0

    if args.command == "apply":
        summary = run_apply(
            args.world,
            args.translations,
            extract_path=args.extract,
            dry_run=args.dry_run,
        )
        print(format_apply(summary))
        return 0

    if args.command == "sandbox" and args.sandbox_command == "import":
        try:
            result = import_world(args.source, name=args.name, replace=args.replace)
        except SandboxTargetExistsError as exc:
            answer = _confirm(
                f"沙盒已有同名地圖 {Path(str(exc.target)).name}，重新匯入會刪除沙盒裡的副本"
                f"（含已寫回的譯文與資源包），翻譯檔不受影響。是否覆蓋？"
            )
            if answer is None:
                raise
            if not answer:
                print("已取消，沒有變更任何檔案。", file=sys.stderr)
                return 2
            result = import_world(args.source, name=args.name, replace=True)
        print(format_import(result))
        return 0

    raise AssertionError(f"未處理的子命令：{args.command}")  # pragma: no cover


def _confirm(question: str) -> bool | None:
    """問一個 [y/N]。**沒有終端機可以問就回傳 `None`**（排程、管線、被別的程式
    呼叫），呼叫端要改成報錯——卡在一個沒人會回答的提示上比報錯糟。"""
    if not sys.stdin.isatty():
        return None
    try:
        answer = input(f"{question} [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")


def _unexpected(exc: Exception, args, started: datetime) -> int:
    """沒被預期的例外：寫日誌，畫面上不印 Python 堆疊。"""
    log = _write_error_log(exc, args, started)
    lines = ["【發生未預期的錯誤】"]
    if log is not None:
        lines.append(f"錯誤資訊已存至 {log}。")
    else:
        lines.append(f"{type(exc).__name__}: {exc}")
    backup = _backup_since(args, started)
    if backup is not None:
        lines.append(f"備份存放於：{backup}")
    print("\n".join(lines), file=sys.stderr)
    return 3


def _write_error_log(exc: Exception, args, started: datetime) -> Path | None:
    """日誌放在沙盒裡（`<沙盒>/mcmt-error.log`）：安全規則 1，任何寫入都要在沙盒
    底下，錯誤日誌也不例外。寫不出去就回傳 `None`，不能讓「記錄錯誤」本身再炸一次。"""
    try:
        path = ensure_writable(sandbox_root() / ERROR_LOG_NAME)
        path.parent.mkdir(parents=True, exist_ok=True)
        header = (
            f"=== {started.isoformat(timespec='seconds')} · mcmt {args.command} · "
            f"Python {platform.python_version()} · {platform.platform()} ===\n"
        )
        body = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        with path.open("a", encoding="utf-8") as handle:
            handle.write(header + body + "\n")
        return path
    except Exception:  # noqa: BLE001
        return None


def _backup_since(args, started: datetime) -> Path | None:
    """這次執行是不是已經建立了備份？有的話，出錯時要告訴使用者放在哪。"""
    if getattr(args, "command", None) != "apply":
        return None
    try:
        folder = sandbox_root() / ".mcmt-backups" / Path(args.world).resolve().name
        fresh = [
            entry
            for entry in folder.iterdir()
            if entry.is_dir() and datetime.fromtimestamp(entry.stat().st_mtime) >= started
        ]
        return max(fresh, key=lambda entry: entry.stat().st_mtime) if fresh else None
    except OSError:
        return None


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
