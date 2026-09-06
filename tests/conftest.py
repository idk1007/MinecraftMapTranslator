# SPDX-License-Identifier: GPL-3.0-or-later
"""測試共用的 region 合成工具，以及指令 splice 的「還解得回來嗎」斷言。

真實 region 切片（`tests/fixtures/regions/`）留給整合測試；單元測試用合成的
位元組，才能精準地製造畸形檔。
"""

import json
import zlib

import amulet_nbt
import pytest

from mcmt.safety.paths import reset_read_log

SECTOR_SIZE = 4096


@pytest.fixture
def project(tmp_path, monkeypatch):
    """一個有 `.git` 標記的假專案，工作目錄設在它底下。

    這樣 `sandbox_root()` 會指到 `tmp_path/sandbox`——測試寫進去的東西是真的
    在一個 sandbox 底下，不必為了測試在圍籬上開 `--force` 這種洞。
    """
    (tmp_path / ".git").mkdir()
    (tmp_path / "sandbox").mkdir()
    monkeypatch.chdir(tmp_path)
    reset_read_log()
    return tmp_path


class RegionBuilder:
    """組出一個結構正確的 region，畸形的情況再事後改位元組。"""

    def __init__(self) -> None:
        self._slots: dict[int, tuple[int, bytes, int]] = {}

    def add(
        self,
        index: int,
        payload: bytes,
        *,
        compression_byte: int = 2,
        timestamp: int = 1_700_000_000,
    ) -> "RegionBuilder":
        self._slots[index] = (compression_byte, payload, timestamp)
        return self

    def add_chunk_nbt(
        self, index: int, root: amulet_nbt.CompoundTag, **kwargs
    ) -> "RegionBuilder":
        data = amulet_nbt.NamedTag(root, "").save_to(compressed=False)
        return self.add(index, zlib.compress(data), **kwargs)

    def build(self) -> bytearray:
        offsets = bytearray(SECTOR_SIZE)
        timestamps = bytearray(SECTOR_SIZE)
        body = bytearray()
        next_sector = 2
        for index in sorted(self._slots):
            compression_byte, payload, timestamp = self._slots[index]
            block = bytearray()
            block += (len(payload) + 1).to_bytes(4, "big")
            block += bytes([compression_byte])
            block += payload
            sectors = (len(block) + SECTOR_SIZE - 1) // SECTOR_SIZE
            block += bytes(sectors * SECTOR_SIZE - len(block))
            offsets[index * 4 : index * 4 + 4] = next_sector.to_bytes(3, "big") + bytes(
                [sectors]
            )
            timestamps[index * 4 : index * 4 + 4] = timestamp.to_bytes(4, "big")
            body += block
            next_sector += sectors
        return offsets + timestamps + body


def set_offset_entry(data: bytearray, index: int, sector: int, count: int) -> None:
    data[index * 4 : index * 4 + 4] = sector.to_bytes(3, "big") + bytes([count])


def set_declared_length(data: bytearray, sector: int, length: int) -> None:
    start = sector * SECTOR_SIZE
    data[start : start + 4] = length.to_bytes(4, "big")


def write_region_file(directory, data: bytes | bytearray, name: str = "r.0.0.mca"):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(bytes(data))
    return path


def modern_chunk(*, data_version: int = 4671) -> amulet_nbt.CompoundTag:
    """1.21 形狀的最小 chunk：只有 DataVersion。"""
    root = amulet_nbt.CompoundTag()
    root["DataVersion"] = amulet_nbt.IntTag(data_version)
    return root


def legacy_chunk() -> amulet_nbt.CompoundTag:
    """1.12 形狀：`Level` 包裝層。"""
    root = amulet_nbt.CompoundTag()
    level = amulet_nbt.CompoundTag()
    level["TileEntities"] = amulet_nbt.ListTag([])
    root["Level"] = level
    return root


# --- 指令 splice 的第二條安全網 -------------------------------------------
#
# `write/command_span.py` 的 docstring 說安全網「全靠 extract 時 span 定位器
# 抓對範圍」。C2 證明那**不夠**：span 可以完全正確，而塞進去的東西**型別**是錯
# 的——把一個 SNBT compound splice 進一個全是字串的 `TAG_List`，位移一個都沒
# 錯，產出的卻是遊戲的指令解析器吃不下的東西（`TAG_List` 在格式層帶單一元素
# 型別 id，CLAUDE.md 二節「NBT list 同型」）。而且 `apply_edits` 回報
# `written 1 / unwritten []`——一次乾淨的成功。
#
# 所以安全網要有第二條獨立的線：**splice 完的引數必須還解得回來**。這條線刻意
# 不看 `node_path`、不看 edit、不重用 `scan/command.py` 的定位邏輯，只拿最後
# 寫進磁碟的那個字串問一句「這還是一條解得開的指令嗎」。

_JSON_ARGUMENT_VERBS = frozenset({"tellraw", "title", "bossbar", "scoreboard"})
_SNBT_ARGUMENT_VERBS = frozenset({"data", "give", "item"})
_NO_ARGUMENT_VERBS = frozenset({"say", "me"})


def assert_command_reparses(command: str) -> None:
    """**任何一次指令 splice 之後，引數都必須還解得回來。**

    依動詞決定用哪個解析器：L1 動詞（`tellraw`／`title`／…）的引數是 JSON，用
    `json.loads`；SNBT 方言的（`data`／`give`／`item`）用
    `amulet_nbt.from_snbt`；`say`／`me` 的參數本來就是純文字，沒有結構化引數可
    以解，跳過。

    **不認得的動詞一律當失敗**——白名單有一天長出新動詞時，這條網不可以安靜地
    變成 no-op（那正是它要防的那種 bug）。反過來，動詞認得但整條指令裡根本沒有
    `{`（例如 `scoreboard objectives add x dummy` 沒有顯示名稱）代表沒有結構化
    引數可 splice，那不是失敗。

    **給 fixture 作者的約束**：`test_every_command_written_back_still_reparses`
    會把這個函式套在來回世界裡的**每一條**指令上，包括從來沒被 splice 過的。
    所以任何被那條測試吃到的世界 fixture，裡面只能有白名單動詞的指令——加一條
    `function ns:x` 或行尾延續的指令（正是未來 gap #A／行尾延續測試會想放的形狀）
    會讓整趟掃描失敗，看起來像 splice 弄壞了。這是設計如此，硬失敗行為不改。
    """
    inner = _after_execute(command).strip()
    verb = inner.split(" ", 1)[0] if inner else ""
    if verb in _NO_ARGUMENT_VERBS:
        return
    if verb not in _JSON_ARGUMENT_VERBS and verb not in _SNBT_ARGUMENT_VERBS:
        raise AssertionError(
            f"assert_command_reparses 不認得動詞 {verb!r}；白名單長出新動詞時"
            f"這條安全網要跟著長，不能安靜地略過：{command!r}"
        )

    start = inner.find("{")
    if start == -1:
        return
    argument = inner[start : _balanced_end(inner, start)]
    try:
        if verb in _JSON_ARGUMENT_VERBS:
            json.loads(argument)
        else:
            amulet_nbt.from_snbt(argument)
    except Exception as exc:  # noqa: BLE001 —— 解不開就是解不開，理由不重要
        raise AssertionError(
            f"splice 之後的指令引數解不回來（{type(exc).__name__}: {exc}）。\n"
            f"  指令：{command!r}\n  引數：{argument!r}"
        ) from exc


def _after_execute(command: str) -> str:
    """剝掉 `execute … run ` 前綴。**刻意不重用
    `scan/command.py::_strip_execute`**——安全網跟被測的定位邏輯共用同一份程式碼
    的話，那份程式碼錯了兩邊會一起錯到同一個地方去。"""
    stripped = command.lstrip()
    if not stripped.startswith("execute"):
        return command
    marker = stripped.find(" run ")
    return stripped[marker + len(" run ") :] if marker != -1 else ""


def _balanced_end(text: str, start: int) -> int:
    """從 `text[start]` 的 `{` 起，回傳配對的 `}` 之後一格的位移。引號內的括號
    不算，反斜線跳脫的引號不算閉合。"""
    depth = 0
    in_string = False
    quote = ""
    index = start
    while index < len(text):
        char = text[index]
        if in_string:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                in_string = False
        elif char in "\"'":
            in_string = True
            quote = char
        elif char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return len(text)
