# SPDX-License-Identifier: GPL-3.0-or-later
"""世代（M5.2）——DataVersion 決定什麼、不決定什麼。

**決定的**：

* 遊戲會不會替這個 chunk 跑 DataFixerUpper（`runs_datafixer`）。低於分水嶺會跑，
  所以裡面的舊式 JSON 是**真內容**；達到或超過就不跑，那些字串在遊戲裡是**字面
  亂碼**（[遊戲實測 M0-3] 對照 [遊戲實測 M4-2/M4-3]）。
* 我們把改動寫回哪個世代（`write_back_version`）——**永遠是讀到的那個**。

**不決定的**：節點是什麼形狀。[實測] DataVersion 4556 的 chunk 裡有 2,340 個舊式
JSON 空字串與 110 個舊式 JSON 物件，所以那個推導已知為錯。形狀一律由
`model/component.py` 逐節點嗅探。**這個模組刻意不提供任何形狀相關的函式**——留著
只會讓人再用一次。

`container` 合約也刻意沒有 `generation` 欄位，同一個理由。
"""

from enum import Enum

__all__ = [
    "DATAFIXER_WATERSHED",
    "TARGET_DATA_VERSION",
    "Generation",
    "generation_of",
    "runs_datafixer",
    "write_back_version",
]

# Java Edition 1.21.11。
TARGET_DATA_VERSION = 4671

# 分水嶺：**達到或超過**這個版本的 chunk 不再跑 DataFixerUpper。
# 合約在 editplan schema 裡以 `minimum: 4325` 表達同一件事，測試會比對兩者。
DATAFIXER_WATERSHED = 4325


class Generation(Enum):
    """一個 chunk 屬於哪一邊。名字講的是**遊戲怎麼對待它**，不是它長什麼樣。"""

    LEGACY = "legacy"
    NATIVE = "native"

    @property
    def legacy_json_is_content(self) -> bool:
        """這個世代裡的舊式 JSON 字串是真內容，還是使用者眼裡的亂碼？

        舊世代：DataFixer 會解析它，是真內容，可以翻。
        新世代：遊戲直接當字面文字算繪，翻了會寫回一個顯示結果同樣是亂碼的字串。
        """
        return self is Generation.LEGACY


def runs_datafixer(data_version: int) -> bool:
    return data_version < DATAFIXER_WATERSHED


def generation_of(data_version: int) -> Generation:
    return Generation.LEGACY if runs_datafixer(data_version) else Generation.NATIVE


def write_back_version(data_version: int) -> int:
    """**工具永不升級格式。** 讀到什麼世代就寫回什麼世代。

    寫成函式而不是註解，是為了讓「升級」變成一個要刻意去改的地方。
    [遊戲實測 M4-4] 遊戲自己會升級玩家走過的 chunk（一張 region 953 個裡升了
    144 個），那是使用者行為造成的，不是我們造成的，我們也不跟著做。
    """
    return data_version
