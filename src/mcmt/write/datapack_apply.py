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

from mcmt.errors import DatapackWriteVerificationError
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

    entries[entry_name] = (info, _encode_entry(document))
    outcome.counts["edits_written"] += written
    backup.protect(path)
    _rewrite_zip(ensure_writable(path), entries, verify_entry=entry_name)
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
    expected = edit["expected_encoding"]
    # `plain_string` 是**欄位**決定的形狀，不是值決定的形狀——任何看值的判斷
    # （`model/component.py` 的 `sniff()`、下面的 `_sniff_json_value()`）都永遠
    # 不會回報它，一個裸字串節點永遠回報 `bare_string`。所以這裡不能直接比對
    # 字串相等：那會讓每一筆 `plain_string` 的 edit 在守門這關就被拒寫，不管
    # 檔案有沒有真的被改過。
    #
    # 這**不是**新發現的問題——`write/common.py` 的 `_guarded_encoding` 在
    # commit 18e0c67 修的就是同一個 bug（`level_name` 整個寫不出去）。兩個寫入器
    # 的守門必須是同一套語意，否則哪天有一個 datapack 來源的 category 走上
    # `plain_string`，同一個 bug 會在這裡原封不動地再爆一次，而且一樣是「拒寫，
    # 但理由寫成『資料包被改過了』」這種會把人帶去查錯方向的失敗。
    # 放寬的範圍與那邊一字不差：只有 `bare_string → plain_string` 這一組。
    if current_encoding == "bare_string" and expected == "plain_string":
        current_encoding = expected
    if current_encoding != expected:
        refuse(
            outcome, edit, "node_changed",
            f"預期 {expected}，現在是 {current_encoding}"
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


def _encode_entry(document: dict) -> bytes:
    """一個 zip 條目的最終位元組。

    抽成函式的理由和 `nbtio/datfile.py::_encode` 一模一樣：不然沒有辦法在測試裡
    製造「編碼器吐出壞位元組」這個情境，而那正是回讀驗證要驗的那一件事。
    """
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


def _write_json_atomically(path: Path, document: dict) -> None:
    # **衍生出來的暫存路徑要自己再過一次 `ensure_writable`。**
    # `nbtio/datfile.py::write_dat` 立的就是這個規矩。「父路徑驗過了，所以從它
    # 衍生的東西都安全」是一個沒有人強制的隱性推論，而 CLAUDE.md 把這種推論在
    # 安全關鍵路徑上明文列為不接受——`.with_name()` 的參數哪天變成別的東西，
    # 這裡就是一個沒有圍籬的寫入點。
    temporary = ensure_writable(path.with_name(path.name + ".mcmt-tmp"))
    data = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")
    temporary.write_bytes(data)
    try:
        json.loads(temporary.read_bytes().decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        temporary.unlink()
        raise DatapackWriteVerificationError(
            f"寫出去的 JSON 讀不回來，已中止：{path}。原檔沒有被動過。"
        ) from exc
    temporary.replace(path)


def _rewrite_zip(path: Path, entries: dict[str, tuple], *, verify_entry: str) -> None:
    """整份重建一個 zip：**暫存 → 回讀驗證 → 原子替換。**

    驗證這一步原本沒有，而 zip 是這個里程碑裡爆炸半徑最大的一次寫入——`.dat`
    編壞了是一個檔案沒了，zip 編壞了是**整份壓縮檔裡的每一個條目**都沒了，包括
    我們根本沒要改的 `pack.mcmeta`、`function/`、`loot_table/`。它卻是這個檔案
    三個寫入器裡驗證最弱的一個：`write_dat` 有回讀解析、`_write_json_atomically`
    有重新 parse，只有這裡是寫完就直接替換。

    驗兩件事，兩件缺一不可：

    * `testzip()` —— 整份壓縮檔的 CRC。回傳 `None` 代表全對，否則回傳第一個
      對不上的條目名。這一項驗的是「我們沒改的那些條目也還好好的」。
    * 剛改過的那個條目重新 `json.loads` —— CRC 對不代表內容對，一份 CRC 完全
      正確的壞 JSON 照樣會讓遊戲載不了這個資料包。

    失敗時**原檔一個位元都沒有被動過**，因為 `replace` 還沒發生；暫存檔在
    `finally` 清掉，不留給下一次寫入撞上。
    """
    temporary = ensure_writable(path.with_name(path.name + ".mcmt-tmp"))
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, (info, data) in sorted(entries.items()):
                archive.writestr(info, data)
        _verify_zip(temporary, path, verify_entry)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _verify_zip(temporary: Path, target: Path, entry_name: str) -> None:
    try:
        with zipfile.ZipFile(str(ensure_readable(temporary))) as archive:
            broken = archive.testzip()
            if broken is not None:
                raise DatapackWriteVerificationError(
                    f"重建出來的 zip 有條目 CRC 對不上（{broken}），已中止："
                    f"{target}。原檔沒有被動過。"
                )
            json.loads(archive.read(entry_name).decode("utf-8"))
    except DatapackWriteVerificationError:
        raise
    except Exception as exc:  # noqa: BLE001 —— 任何讀不回來的理由都一樣致命
        raise DatapackWriteVerificationError(
            f"重建出來的 zip 讀不回來，已中止：{target}。原檔沒有被動過。"
            f"原因：{type(exc).__name__}: {exc}"
        ) from exc


def _split(world: Path, relative: str) -> tuple[str | None, str | None]:
    """`datapacks/<name>.zip/<zip 內路徑>` → `(zip 相對路徑, zip 內路徑)`；
    資料夾形式回傳 `(None, None)`。datapack 一定是 `datapacks/` 的直接子項，
    不會巢狀，所以只要找第一個以 `.zip` 結尾的路徑片段。"""
    parts = relative.replace("\\", "/").split("/")
    for index, part in enumerate(parts):
        if part.endswith(".zip"):
            return "/".join(parts[: index + 1]), "/".join(parts[index + 1 :])
    return None, None
