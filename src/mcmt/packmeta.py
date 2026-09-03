# SPDX-License-Identifier: GPL-3.0-or-later
"""`pack.mcmeta` 的 `supported_formats` 前向加寬——`resources.zip` 與 datapack 共用。

[實測 2026-09-03，見 `SPIKE_RESULT.md`「Minecraft 26.2 遊戲實測」] 只要遊戲的格式號
高過一個 pack 宣告的 `supported_formats.max_inclusive`，整個 pack 會被判過期、拒絕
載入，我們併進去的東西（`resources.zip` 的 lang 檔、datapack 的 advancement 譯文）
跟著失效——`apply` 正確寫進了檔案，但玩家在遊戲裡一個字都看不到。

**對策**：把 `max_inclusive` 推到一個實質無上限的天花板（`FORWARD_PACK_FORMAT`）。
下限維持 pack 自己宣告的值——那個地板可能是 pack 其他內容真的需要的（材質、模型、
loot table 語法、函式語法），替它往下開等於謊報這個 pack 為舊版做過。

**取捨**（刻意接受，見 `backends/resourcepack/pack.py` 模組 docstring）：未來 Mojang
真的動了資源包／資料包的載入語意（不是只改版本號）時，這個 pack 會**默默失效**
（遊戲仍載入、內容不生效），不是一個乾淨的錯誤。單人翻地圖的工具不追每個版本。
"""

from typing import Any

__all__ = ["FORWARD_PACK_FORMAT", "widen_supported_formats"]

FORWARD_PACK_FORMAT = 9999  # 實質無上限


def widen_supported_formats(
    meta: dict[str, Any],
) -> tuple[dict[str, Any], bool, str]:
    """回傳 `(加寬後的 meta, 有沒有改, 給人看的說明)`。

    **冪等**：`supported_formats.max_inclusive` 已經開到 `FORWARD_PACK_FORMAT`（或
    更高）時原封回傳、`changed` 為 `False`、說明為空字串。呼叫端可以無腦每次都呼叫，
    不必自己記「這個 pack 是不是已經加寬過了」。
    """
    pack = dict(meta.get("pack") or {})
    declared = pack.get("pack_format")
    supported = pack.get("supported_formats")

    if (
        isinstance(supported, dict)
        and isinstance(supported.get("max_inclusive"), int)
        and supported["max_inclusive"] >= FORWARD_PACK_FORMAT
    ):
        return meta, False, ""

    low: int | None = declared if isinstance(declared, int) else None
    if isinstance(supported, dict) and isinstance(supported.get("min_inclusive"), int):
        low = supported["min_inclusive"] if low is None else min(low, supported["min_inclusive"])
    if low is None:
        # pack.mcmeta 沒有任何可用的下限資訊（連 `pack_format` 都不是整數）。
        # 不亂猜一個下限——那是呼叫端該回報「這份 pack.mcmeta 讀不懂」的情境。
        return meta, False, ""

    pack["supported_formats"] = {
        "min_inclusive": low,
        "max_inclusive": FORWARD_PACK_FORMAT,
    }
    updated = dict(meta)
    updated["pack"] = pack
    note = (
        f"這個 pack 的 pack.mcmeta 宣告 pack_format {declared}，沒有把 supported_formats "
        f"開向未來——新版遊戲會拒絕整個 pack（連我們併進去的內容一起）。已把 "
        f"supported_formats 設成 {low}–{FORWARD_PACK_FORMAT}，未更動它宣告的 pack_format。"
    )
    return updated, True, note
