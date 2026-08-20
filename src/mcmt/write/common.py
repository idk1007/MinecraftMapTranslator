# SPDX-License-Identifier: GPL-3.0-or-later
"""legacy 與 native 都需要的那一點點共同邏輯（M11.1）。**高風險目錄。**

這裡**只放兩者真的完全相同的東西**：editplan 的 value 該長成什麼 component（那是
合約定義的），以及佔位符殘留的檢查。

形狀怎麼寫進 NBT、list 要不要提升——那些是不對稱的部分，各自在自己的檔案裡。
把它們搬到這裡就是 CLAUDE.md 說的「用 if/else 把不對稱藏起來，然後某天套錯」。
"""

import re
from typing import Any

from mcmt.errors import PlaceholderResidueError

__all__ = ["component_for", "refuse_residue"]

_TOKEN = re.compile(r"\[\[\d+\]\]")


def refuse_residue(text: str) -> None:
    """任何 `literal` 的文字若殘留 `[[n]]`，**拒絕整份 plan**。

    不是「跳過這一筆」：殘留代表上游（後端或驗證）算錯了，而算錯的東西不會只錯一筆。
    寫出去玩家會看到那串記號。
    """
    found = _TOKEN.findall(text)
    if found:
        raise PlaceholderResidueError(text=text, tokens=found)


def component_for(value: dict[str, Any]) -> Any:
    """editplan 的 value → 一棵 component（純 Python，還沒變成 NBT）。"""
    kind = value.get("kind")

    if kind == "translate":
        component: dict[str, Any] = {"translate": value["key"]}
        if value.get("fallback"):
            component["fallback"] = value["fallback"]
        component.update(value.get("style") or {})
        return component

    if kind == "literal":
        refuse_residue(value["text"])
        component = {"text": value["text"]}
        component.update(value.get("style") or {})
        return component

    if kind == "component":
        return value["tree"]

    raise ValueError(f"不認得的寫入值種類：{kind!r}")
