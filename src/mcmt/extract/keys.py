# SPDX-License-Identifier: GPL-3.0-or-later
"""translate key 與 unit id 的生成（M7.1）。

```
translateKey = <namespace>.<category>.<discriminator>[.<segment_index>]
unitId       = u:<category>:<discriminator>
```

`discriminator` 在兩者中是**同一個字串，由同一個函式產生一次，永不分岔**。分岔的
後果是翻譯對不回節點，而且不會有任何錯誤訊息。

hash 輸入是**攤平後的 `source.text`，不是 raw**——帶 `extra` 的樹沒有單一 raw，而
`text` 同時編碼了字詞與段落切點，那正是決定「這是不是同一個翻譯單位」的東西。樣式的
**值**不進 hash（同一句話的金色版與紅色版是同一個翻譯單位），但**切點**進（它在
`text` 裡）。

`SCHEMA_VERSION` 也進 hash 輸入：合約改版時所有 key 一起換，舊的 translations 不會
安靜地半套用上。

碰撞**硬失敗**：`_1`、`_2` 依序追加，兩邊的 hash 輸入都記進 keymap。**絕不靜默覆蓋**
——後果是兩段不同的文字共用一個譯文，而且沒有任何跡象。
"""

import unicodedata
from hashlib import blake2b

from mcmt.model import SCHEMA_VERSION

__all__ = [
    "KeyRegistry",
    "discriminator_for",
    "hash_input",
    "normalize",
    "translate_key",
    "unit_id",
]

# 單元分隔符。不會出現在文字裡，所以拼接不會有歧義。
_SEP = "\x1f"
_DIGEST_BYTES = 8  # 16 hex = 64 bits


def normalize(text: str) -> str:
    """hash 之前的正規化。**只做兩件事，其餘一律不動。**

    1. Unicode NFC
    2. 換行統一為 LF

    **不做**空白處理（不 strip、不折疊、不移除）、**不做**大小寫轉換、**不移除** § 碼。

    「不碰空白」是硬性的：告示牌用前導空白做置中排版，`"  歡迎  "` 與 `"歡迎"` 是
    不同的視覺結果，折疊空白會讓它們塌成同一個 key，排版全毀。
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", text)


def hash_input(category: str, text: str) -> str:
    return f"{SCHEMA_VERSION}{_SEP}{category}{_SEP}{normalize(text)}"


def _digest(text: str) -> str:
    return blake2b(text.encode("utf-8"), digest_size=_DIGEST_BYTES).hexdigest()


def discriminator_for(category: str, text: str) -> str:
    """16 hex。碰撞處理要走 `KeyRegistry`，這個函式只算裸 digest。"""
    return _digest(hash_input(category, text))


def unit_id(category: str, text: str, *, discriminator: str | None = None) -> str:
    return f"u:{category}:{discriminator or discriminator_for(category, text)}"


def translate_key(
    namespace: str,
    category: str,
    text: str,
    *,
    discriminator: str | None = None,
    segment: int | None = None,
) -> str:
    """`segment` **只有 `collapsible` 為 false 時才給**——它是段落序號。

    消歧一律走 discriminator 裡的 `_<n>`，兩者不共用同一個位置。
    """
    digest = discriminator or discriminator_for(category, text)
    key = f"{namespace}.{category}.{digest}"
    return key if segment is None else f"{key}.{segment}"


class KeyRegistry:
    """一次 extract 的所有 key。碰撞在這裡被發現、被記錄、被解決。"""

    def __init__(self) -> None:
        self._taken: dict[str, str] = {}  # discriminator -> hash_input
        self._flags: dict[str, set[str]] = {}
        self.collisions: list[dict] = []

    def register(self, category: str, text: str) -> str:
        """回傳這段文字該用的 discriminator，必要時帶 `_<n>`。"""
        source = hash_input(category, text)
        base = _digest(source)

        existing = self._taken.get(base)
        if existing is None:
            self._taken[base] = source
            return base
        if existing == source:
            return base  # 同一段文字再出現一次，本來就該是同一個 key

        # 真的撞了：不同的 hash 輸入算出同一個 digest。
        suffix = 1
        while True:
            candidate = f"{base}_{suffix}"
            taken = self._taken.get(candidate)
            if taken is None:
                self._taken[candidate] = source
                self._flags.setdefault(candidate, set()).add("collision_resolved")
                self.collisions.append(
                    {
                        "digest": base,
                        "hash_inputs": [existing, source],
                        "resolution": candidate,
                    }
                )
                return candidate
            if taken == source:
                return candidate
            suffix += 1

    def flags_for(self, discriminator: str) -> set[str]:
        return set(self._flags.get(discriminator, ()))

    def keymap(self) -> dict:
        """`keymap.json` 的內容。**進版控**——它是專案的一部分，不是產物。"""
        return {"schema_version": SCHEMA_VERSION, "collisions": self.collisions}
