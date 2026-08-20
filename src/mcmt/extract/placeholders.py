# SPDX-License-Identifier: GPL-3.0-or-later
"""佔位符的驗證與還原（M7.2）。

譯文的 `[[n]]` 多重集合必須與原文**完全一致**——不多、不少、不重複。

**這是 hard fail 不是 warn。** `§l`、`§n` 這類格式碼持續生效到 `§r` 或行尾，少一個
標記就是顏色／粗體染到整行結尾。違反者不寫入，進 `apply_report.unwritten`。

順序**可以**不同——中文語序重排是正常的。

兩個附帶規則：

* 原文含字面 `[[n]]` 時，攤平時已經轉義成 `[[\\n]]`。那不是我們的標記，但它**必須
  原樣留在譯文裡**——它是使用者看得到的字。
* **佔位符全數前移**（`[[0]][[1]]文字`）集合檢查會通過但語意全毀：兩個樣式段變成
  一個空段加一個全文段。單獨檢查並警告，交人工複審。
"""

import re
from collections import Counter
from dataclasses import dataclass, field

__all__ = ["Validation", "tokens_in", "unescape", "validate"]

# 我們插的標記。轉義過的 `[[\0]]` 不會命中——中間多了一個反斜線。
_TOKEN = re.compile(r"\[\[(\d+)\]\]")

# 原文自己帶的、被轉義過的字面文字。
_ESCAPED = re.compile(r"\[\[\\(\d+)\]\]")

# 兩個標記中間沒有任何字：樣式段被壓成空的。
_ADJACENT = re.compile(r"\[\[\d+\]\]\s*\[\[\d+\]\]")


@dataclass
class Validation:
    ok: bool
    reason: str | None = None
    detail: str = ""
    warnings: list[str] = field(default_factory=list)


def tokens_in(text: str) -> list[str]:
    """依出現順序列出**我們插的**標記。轉義過的字面文字不算。"""
    return [match.group(0) for match in _TOKEN.finditer(text)]


def unescape(text: str) -> str:
    r"""把 `[[\n]]` 還原成 `[[n]]`。寫回節點前的最後一步。"""
    return _ESCAPED.sub(lambda m: f"[[{m.group(1)}]]", text)


def validate(source: str, target: str) -> Validation:
    """比對原文與譯文的佔位符。"""
    if not target:
        # 空 target 是「還沒翻」，那是另一件事——報成佔位符錯誤只會讓人找錯方向。
        return Validation(ok=False, reason="empty_translation")

    wanted = Counter(tokens_in(source))
    found = Counter(tokens_in(target))
    if wanted != found:
        missing = sorted((wanted - found).elements())
        extra = sorted((found - wanted).elements())
        return Validation(
            ok=False,
            reason="placeholder_mismatch",
            detail=f"少了 {missing}、多了 {extra}",
        )

    escaped_wanted = Counter(_ESCAPED.findall(source))
    escaped_found = Counter(_ESCAPED.findall(target))
    if escaped_wanted != escaped_found:
        return Validation(
            ok=False,
            reason="escaped_literal_lost",
            detail=f"原文的字面文字沒有原樣留下：{sorted((escaped_wanted - escaped_found).elements())}",
        )

    warnings = []
    if len(wanted) > 1 and _ADJACENT.search(target):
        # 集合對得上，樣式卻全毀：兩個樣式段變成一個空段加一個全文段。
        warnings.append("placeholder_front_loaded")
    return Validation(ok=True, warnings=warnings)
