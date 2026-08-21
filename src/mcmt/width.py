# SPDX-License-Identifier: GPL-3.0-or-later
"""字寬與寬度預算（M8）。

**這個模組的存在理由是給人看，不是給機器擋。** 譯者得先知道「這行只放得下六個
中文字」才有辦法斟酌用詞；事後才報超寬對他沒有幫助（`docs/STATUS.md`）。所以數字
走進 `translations.<lang>.json` 的 `note`，而不是只走進報告。

## 數字放在資料裡，不放在程式裡

全部在 `fontdata/vanilla_v1.json`，每一項帶 `evidence`（四級制）與 `calibrated`。
校準是**改資料**，不是改程式——`tools/calibrate_font_widths.py --record` 就只重寫
那一個檔案。這樣「哪些數字量過、哪些還是猜的」永遠只有一個地方要看。

## 校準完成前一律 warn

`enforcement_for()` 讀的是 `calibrated` 旗標，不是某個常數。旗標翻成 true 之前，
沒有任何路徑能把 `sign` 升成 `error`（CLAUDE.md C 題），而且有測試守著。

## § 碼是內容，但不佔像素

key 生成時 `§` **不移除**（它是內容的一部分，CLAUDE.md 三節的 normalize 第 5 條），
但算繪時它不畫出來。兩件事不衝突：`measure()` 跳過格式碼，只是**粗體之後每個字
多 1px**——那個效果持續到 `§r` 或行尾，和 `[[n]]` 少一個的後果是同一個機制。

[遊戲實測 M11-2] 吊掛告示牌比一般告示牌窄很多（7 個 CJK 字被截掉，同樣長度在一般
告示牌上完全正常），所以兩者分開量，不共用一個數字。
"""

import json
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "FONT_DATA",
    "Budget",
    "advance_of",
    "budget_for",
    "cjk_capacity",
    "enforcement_for",
    "measure",
]

_DATA_PATH = Path(__file__).resolve().parent / "fontdata" / "vanilla_v1.json"
FONT_DATA = json.loads(_DATA_PATH.read_text("utf-8"))

MEASUREMENT_ID = FONT_DATA["id"]

_SIGMA = "§"
# `§r` 重設全部格式。其餘的碼在寬度上只有粗體有影響（顏色不改字寬）。
_BOLD = "l"
_RESET = "r"


@dataclass(frozen=True)
class Budget:
    category: str
    max_width_px: int
    max_lines: int
    wrap: str
    calibrated: bool
    evidence: str
    note: str


def budget_for(category: str) -> Budget | None:
    """這個 category 的寬度預算。沒有預算就是 None——**不要回一個假的大數字**。"""
    raw = FONT_DATA["budgets"].get(category)
    if raw is None:
        return None
    return Budget(
        category=category,
        max_width_px=raw["max_width_px"],
        max_lines=raw["max_lines"],
        wrap=raw["wrap"],
        calibrated=raw["calibrated"],
        evidence=raw["evidence"],
        note=raw.get("note", ""),
    )


def advance_of(character: str) -> int:
    """一個字元的前進寬度（px，含字元間的 1px 間隔）。"""
    advance = FONT_DATA["advances"].get(character)
    if advance is not None:
        return advance
    if _is_wide(character):
        return FONT_DATA["cjk_advance"]
    return FONT_DATA["default_advance"]


def measure(text: str) -> int:
    """整串文字的算繪寬度（px）。§ 碼不佔寬度，但粗體讓其後每個字多 1px。"""
    total = 0
    bold = False
    index = 0
    while index < len(text):
        character = text[index]
        if character == _SIGMA and index + 1 < len(text):
            code = text[index + 1].lower()
            if code == _BOLD:
                bold = True
            elif code == _RESET or code in "0123456789abcdef":
                # 顏色碼會重設格式——`§l§c文字` 的粗體被 `§c` 洗掉。
                # 這與 `lang.py` 把顏色寫在格式之前是同一條規則的兩面。
                bold = False
            index += 2
            continue
        total += advance_of(character) + (FONT_DATA["bold_extra"] if bold else 0)
        index += 1
    return total


def cjk_capacity(category: str) -> int | None:
    """這一行放得下幾個中文字。**這才是譯者看得懂的單位**，px 不是。"""
    budget = budget_for(category)
    if budget is None:
        return None
    return budget.max_width_px // FONT_DATA["cjk_advance"]


def enforcement_for(category: str) -> str:
    """`constraints.enforcement`。

    **校準完成前一律 `warn`。** 判準是資料裡的 `calibrated` 旗標——升級成 `error`
    是資料的決定，不是這裡某個 if 的決定。
    """
    budget = budget_for(category)
    if budget is None:
        return "none"
    return "error" if budget.calibrated else "warn"


def _is_wide(character: str) -> bool:
    """CJK 與全形標點走另一張表。

    刻意不引入 `unicodedata.east_asian_width`：那張表把「模稜兩可」（A）的字元也算
    寬，而那類在原版字型裡是半形。範圍列舉少一段就少量到一類字，多一段就會把半形
    字算成兩倍寬——兩種錯都看得見（校準板上會對不上），比一個看不出來的近似好。
    """
    code = ord(character)
    return any(
        low <= code <= high
        for low, high in (
            (0x1100, 0x115F),  # 韓文字母
            (0x2E80, 0x303E),  # CJK 部首、標點
            (0x3041, 0x33FF),  # 假名、注音、諺文、相容字
            (0x3400, 0x4DBF),  # 擴充 A
            (0x4E00, 0x9FFF),  # 基本區
            (0xA000, 0xA4CF),  # 彝文
            (0xAC00, 0xD7A3),  # 諺文音節
            (0xF900, 0xFAFF),  # 相容表意
            (0xFE30, 0xFE6F),  # 相容形式
            (0xFF00, 0xFF60),  # 全形
            (0xFFE0, 0xFFE6),
            (0x20000, 0x2FFFD),  # 擴充 B 之後
        )
    )
