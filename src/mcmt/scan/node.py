# SPDX-License-Identifier: GPL-3.0-or-later
"""掃描層的兩個資料形狀。

`TextNode` 原本住在 `sources/region.py`，M13 把它搬出來——七個來源都要用它，
留在其中一個來源裡會讓其他六個 import 一個「別人的」模組。

`ScannedNode` 是 `TextNode` 加上**它在哪個容器裡**。容器由來源自己產生，因為只有
來源知道自己讀的是什麼檔案、那個檔案的 DataVersion 是多少、它算 region chunk 還是
level.dat。
"""

from dataclasses import dataclass
from typing import Any

from mcmt.model.node import NodePath

__all__ = ["ScannedNode", "TextNode"]


@dataclass(frozen=True)
class TextNode:
    """一個等著被判形狀的文字節點，以及它在世界裡的位置。"""

    path: NodePath
    tag: Any
    category: str
    anchor: dict[str, Any] | None = None
    list_context: dict[str, Any] | None = None


@dataclass(frozen=True)
class ScannedNode:
    """一個文字節點 + 它所在的容器（寫回去的地址）。"""

    node: TextNode
    container: dict[str, Any]
