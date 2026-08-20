# SPDX-License-Identifier: GPL-3.0-or-later
"""第 3 層：規則標記。決定一個節點該不該翻、屬於哪一類。

規則**只加標籤**，不刪標籤——這是不動點迭代能收斂的前提。要表達「不翻」就加一個
`do_not_translate`，不是把 `translatable` 拿掉。
"""
