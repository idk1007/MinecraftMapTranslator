# SPDX-License-Identifier: GPL-3.0-or-later
"""datapack advancement JSON 的寫入器（M13.7）。**高風險目錄。**

**保證只到「檔案重寫」**：資料夾形式直接覆寫該 JSON 檔（暫存 → 回讀驗證 →
原子替換）；zip 形式**整份重建**（沿用 `write/../backends/resourcepack/pack.py`
的做法：既有條目原樣搬運，只重寫我們動過的那幾個）。

**這裡走純 Python `dict`/`list` 樹，不透過 `amulet_nbt`。** advancement JSON
本來就是 JSON，往 `display.title` 塞一個 `{"translate": key}` 的 Python dict，
直接就是最終要 `json.dump` 出去的東西——不需要先轉成 NBT 再轉回來。這是這個
寫入器和 `write/common.py` 的 `apply_edit_to_compound` 唯一的差異：走訪邏輯是
同一套三步驟（照 node_path 走 → 比對 expected_encoding → 按 value.kind 決定
寫什麼），型別檢查換成 dict/list。

**這是工具第一次改動地圖自己的檔案**（不是它的存檔資料，是它的資料包）。
[遊戲實測 M4-5] 的教訓是這類事要在報告裡講清楚——`apply.py` 的呼叫端（`cli/
apply.py`）沿用既有的 `warnings` 機制，這裡負責的是把 datapack 這件事本身
記進 `files_rewritten`，讓使用者從報告數字上就看得出「有東西動到了資料包」。
"""

import json
import zipfile
from pathlib import Path
from typing import Any

from mcmt.model.node import NodePath
from mcmt.safety.backup import BackupSet
from mcmt.safety.paths import ensure_readable, ensure_writable
from mcmt.write.common import ApplyOutcome, component_for, refuse

__all__ = ["apply_to_datapack_file"]


def apply_to_datapack_file(
    world: Path,
    relative: str,
    edits: list[dict],
    outcome: ApplyOutcome,
    backup: BackupSet,
) -> None:
    """**`relative` 是 `apply_editplan` 的 `by_file` 分組鍵**（`container["path"]`
    的原文），所以這裡收到的 `edits` 全部指向同一個 JSON 檔——資料夾形式時就是
    那個檔案本身；zip 形式時是同一個 zip **裡的同一個條目**（container.path 對
    zip 內條目編碼成 `<zip 相對路徑>/<條目路徑>` 的完整字串，見 Task 5）。

    **這裡不做「同一個 zip 裡跨檔案批次重建」**：`by_file` 是按 `container.path`
    整段字串分組的，zip 裡兩個不同的 JSON 檔（`a.json`／`b.json`）有不同的
    `container.path`，天生就會落進兩個分組、各自呼叫這個函式一次。若同一個 zip
    有多個檔案要改，這個函式會被 `apply_editplan` 依序呼叫多次，**每次都各自
    重讀、重寫整個 zip**——不是最有效率的做法（比對 region 那邊「同一張 region
    的所有 chunk 一次寫完」），但每次呼叫本身是自洽正確的：後一次呼叫讀到的是
    前一次已經寫回磁碟的版本，最終所有檔案的修改都會保住。datapack 的 zip 通常
    不大（不是 87MB 的 `resources.zip`），這個效率問題目前不值得為了它在
    `apply_editplan` 加一層「依 zip 路徑而非完整 container.path 分組」的特例。
    """
    zip_path, entry = _split(world, relative)
    if zip_path is not None:
        _apply_to_zip_entry(world, zip_path, entry, edits, outcome, backup)
        return
    _apply_to_folder_file(world, relative, edits, outcome, backup)


def _apply_to_folder_file(
    world: Path, relative: str, edits: list[dict], outcome: ApplyOutcome, backup: BackupSet
) -> None:
    path = world / relative
    if not path.exists():
        for edit in edits:
            refuse(outcome, edit, "node_missing", f"找不到 {relative}")
        return

    try:
        document = json.loads(ensure_readable(path).read_bytes().decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        for edit in edits:
            refuse(outcome, edit, "chunk_unreadable", str(exc))
        return

    written = 0
    for edit in edits:
        if _apply_edit_to_json(document, edit, outcome):
            written += 1
    if not written:
        return

    outcome.counts["edits_written"] += written
    backup.protect(path)
    _write_json_atomically(ensure_writable(path), document)
    outcome.counts["files_rewritten"] += 1


def _apply_to_zip_entry(
    world: Path,
    zip_relative: str,
    entry_name: str,
    edits: list[dict],
    outcome: ApplyOutcome,
    backup: BackupSet,
) -> None:
    """改 zip 裡**一個**條目（`edits` 全部指向同一個 `entry_name`——見
    `apply_to_datapack_file` 的說明）。整份 zip 都要重讀一次才能改一個條目，
    其餘條目原樣搬運。"""
    path = world / zip_relative
    if not path.exists():
        for edit in edits:
            refuse(outcome, edit, "node_missing", f"找不到 {zip_relative}")
        return

    try:
        with zipfile.ZipFile(str(ensure_readable(path))) as archive:
            entries = {info.filename: (info, archive.read(info.filename)) for info in archive.infolist()}
    except (zipfile.BadZipFile, OSError) as exc:
        for edit in edits:
            refuse(outcome, edit, "chunk_unreadable", str(exc))
        return

    info, raw = entries.get(entry_name, (None, None))
    if info is None:
        for edit in edits:
            refuse(outcome, edit, "node_missing", f"zip 裡找不到 {entry_name}")
        return

    try:
        document = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        for edit in edits:
            refuse(outcome, edit, "chunk_unreadable", str(exc))
        return

    written = 0
    for edit in edits:
        if _apply_edit_to_json(document, edit, outcome):
            written += 1
    if not written:
        return

    entries[entry_name] = (info, json.dumps(document, ensure_ascii=False).encode("utf-8"))
    outcome.counts["edits_written"] += written
    backup.protect(path)
    _rewrite_zip(ensure_writable(path), entries)
    outcome.counts["files_rewritten"] += 1


def _apply_edit_to_json(document: dict, edit: dict, outcome: ApplyOutcome) -> bool:
    """`apply_edit_to_compound` 的純 Python 版本——同一套三步驟，型別檢查換成
    `dict`/`list`。advancement 的節點永遠以 `key` 結尾（`display.title`/
    `display.description`），不需要處理 `index` 結尾。"""
    steps = list(NodePath.from_json(edit["node_path"]))
    if not steps or steps[-1].t != "key":
        refuse(outcome, edit, "unsupported_encoding", "datapack 寫入路徑只支援 key 結尾")
        return False

    try:
        parent = _resolve(document, steps[:-1])
    except (KeyError, IndexError, TypeError) as exc:
        refuse(outcome, edit, "node_missing", str(exc))
        return False

    name = steps[-1].name
    if not isinstance(parent, dict) or name not in parent:
        refuse(outcome, edit, "node_missing", f"找不到鍵 {name}")
        return False

    current_encoding = _sniff_json_value(parent[name])
    if current_encoding is None:
        refuse(outcome, edit, "unsupported_encoding", "這個節點不是文字節點")
        return False
    if current_encoding != edit["expected_encoding"]:
        refuse(
            outcome, edit, "node_changed",
            f"預期 {edit['expected_encoding']}，現在是 {current_encoding}"
            f"——資料包在 extract 之後被改過了",
        )
        return False

    parent[name] = component_for(edit["value"])
    return True


def _sniff_json_value(value: Any) -> str | None:
    """純 Python 值的最小形狀判斷——不透過 `amulet_nbt.sniff()`（那個只吃
    `amulet_nbt` 標籤）。只判三種，advancement 值只會是這三種之一。"""
    if isinstance(value, str):
        return "bare_string"
    if isinstance(value, dict):
        return "text_compound" if set(value) == {"text"} else "compound_tree"
    if isinstance(value, list):
        return "compound_tree"
    return None


def _resolve(document, steps):
    current = document
    for step in steps:
        if step.t == "key":
            if not isinstance(current, dict) or step.name not in current:
                raise KeyError(f"找不到鍵 {step.name}")
            current = current[step.name]
        elif step.t == "index":
            current = current[step.i]
        else:
            raise KeyError("datapack 寫入路徑不支援 decode 步驟")
    return current


def _write_json_atomically(path: Path, document: dict) -> None:
    temporary = path.with_name(path.name + ".mcmt-tmp")
    data = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")
    temporary.write_bytes(data)
    try:
        json.loads(temporary.read_bytes().decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        temporary.unlink()
        raise ValueError(f"寫出去的 JSON 讀不回來，已中止：{path}") from exc
    temporary.replace(path)


def _rewrite_zip(path: Path, entries: dict[str, tuple]) -> None:
    temporary = path.with_name(path.name + ".mcmt-tmp")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, (info, data) in sorted(entries.items()):
                archive.writestr(info, data)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _split(world: Path, relative: str) -> tuple[str | None, str | None]:
    """`datapacks/<name>.zip/<zip 內路徑>` → `(zip 相對路徑, zip 內路徑)`；
    資料夾形式回傳 `(None, None)`。datapack 一定是 `datapacks/` 的直接子項，
    不會巢狀，所以只要找第一個以 `.zip` 結尾的路徑片段。"""
    parts = relative.replace("\\", "/").split("/")
    for index, part in enumerate(parts):
        if part.endswith(".zip"):
            return "/".join(parts[: index + 1]), "/".join(parts[index + 1 :])
    return None, None
