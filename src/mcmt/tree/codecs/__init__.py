# SPDX-License-Identifier: GPL-3.0-or-later
"""巢狀文件的讀寫器（M5.7）。

`node_path` 的 `decode` 步驟說「這裡以下是另一份文件」——指令字串裡包 SNBT、
SNBT 裡再包 component。codec 就是那份文件的讀寫器。

每個 codec 都要誠實回答 `faithful_round_trip`：**重新編碼之後還是同一串位元組嗎？**
不是的話，寫入層就不能整份重編（那會改到沒被要求改的地方），只能用 `decode.span`
做位移替換——而位移替換要求同一父字串的編輯**由後往前**（`model/node.span_order`）。

    json_component  ✅ 忠實（[實測] 真實地圖 78/78 位元組一致，compact 形式）
    lang_json       ✅ 讀寬容、寫嚴格
    snbt            ❌ **不忠實**：amulet-nbt 的 to_snbt() 會把鍵排序
    command         ⛔ 尚未實作，明確拒絕
"""

from mcmt.model.node import Codec
from mcmt.tree.codecs import command, json_component, lang_json, snbt

__all__ = ["codec_for", "registry"]

_REGISTRY = {
    Codec.JSON_COMPONENT: json_component,
    Codec.SNBT: snbt,
    Codec.COMMAND: command,
    Codec.LANG_JSON: lang_json,
}


def registry() -> dict:
    """codec 名稱 → 實作。合約的 enum 少一個實作就是執行到一半才發現不支援。"""
    return dict(_REGISTRY)


def codec_for(codec: Codec | str):
    return _REGISTRY[Codec(codec)]
