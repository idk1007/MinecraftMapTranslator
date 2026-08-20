# SPDX-License-Identifier: GPL-3.0-or-later
"""component 樹的攤平與段落切分（M5.3）。

**§ 舊碼與結構化格式是同一套佔位符機制的兩種輸入，不是兩條路**（CLAUDE.md 三節）。
一個 `§c` 開啟的樣式段，和一個 `{"text":…,"color":"red"}` 子節點開啟的樣式段，在
`source.text` 裡都是一個 `[[n]]`。LLM 看到的是不透明記號，不知道也不需要知道差別。

    {"translate":"mcp.Cost_","fallback":"Cost:",
     "extra":[{"translate":"mcp.…","fallback":" 5 Coins","color":"gold"}]}

    → text      "[[0]]Cost:[[1]] 5 Coins"
      plain     "Cost: 5 Coins"
      segments  [structural(σ✗), structural(σ✗)]
      styles    [{translate,fallback}, {translate,fallback,color}]
      skeleton  {"type":"translate","segment":0,
                 "extra":[{"type":"translate","segment":1}]}

三件東西分別住在不同地方，理由見 CLAUDE.md：**段落切點**進 `unit`（切點不同必然
是不同單位）、**樣式值**進 `occurrence`（同一句話的金色版與紅色版是同一個翻譯
單位）、**骨架**進 `occurrence`（重建時要照著原樹長回去）。

** 不攤平，只原樣帶走。** [實測] MP2 的告示牌有 translate 參數，內容是玩家名
與分數這類**執行期產物**——不是地圖作者寫的字，翻它沒有意義。但它必須被帶著走，
否則重建時整個參數會消失。
輸入是**已經解碼過的**純 Python 結構（`str` / `dict` / `list`）：原生 NBT 由掃描層
轉成 dict，舊式 JSON 由嗅探器解析成 dict。到了這裡兩者形狀相同，所以只有一份攤平
邏輯——寫入端的 legacy/native 不對稱是**寫**的事，不是**讀**的事。
"""

import re
from dataclasses import dataclass, field
from typing import Any

__all__ = ["Flattened", "Segment", "flatten"]

# § 後面接一個顏色/格式字元。連續的 § 碼算同一段（`§c§l` 是紅色粗體，不是兩段）。
_SIGMA_RUN = re.compile(r"(?:§[0-9a-fk-orA-FK-OR])+")

# 原文自己長得像佔位符時要轉義，否則驗證會把它算成我們插的標記。
_PLACEHOLDER_LIKE = re.compile(r"\[\[(\d+)\]\]")

# 被轉義成 [[反斜線 n]] 的字面文字不會被這個吃掉——它只吃我們自己插的標記。
_TOKEN = re.compile(r"\[\[\d+\]\]")

# § 碼表達不了這些，一個就足以讓整棵樹不能塌成一個 lang 值。
_NON_SIGMA_FIELDS = frozenset({"click_event", "hover_event", "font", "insertion"})

# 節點裡「不是樣式」的鍵：文字內容與子節點。
_TEXT_KEYS = frozenset({"text", ""})
_STRUCTURE_KEYS = frozenset({"extra"})


@dataclass(frozen=True)
class Segment:
    """`source.segments[n]`——`[[n]]` 開啟的是什麼樣的一段。

    只帶 `kind` 與 `sigma_expressible`：這兩個決定**單位身分與可塌縮性**。樣式的
    實際**值**在 `Flattened.styles`（per-occurrence），不進這裡。
    """

    kind: str  # "none" | "legacy" | "structural"
    sigma_expressible: bool


@dataclass
class Flattened:
    text: str = ""
    plain: str = ""
    segments: list[Segment] = field(default_factory=list)
    styles: list[dict[str, Any]] = field(default_factory=list)
    skeleton: dict[str, Any] | None = None
    escaped_literals: list[str] = field(default_factory=list)
    # 攤平過程的暫存：每個段落的文字。要走完全部才知道有幾段、才知道該不該插
    # 標記，所以先收著。不進合約。
    _runs: list[str] = field(default_factory=list, repr=False)

    @property
    def collapsible(self) -> bool:
        """整棵樹能不能塌成一個 `{translate: key}`，樣式轉成 § 碼進 lang 值。

        一段不能用 § 表達就不行——那時要重建整棵樹，每段一個 key。
        """
        return all(s.sigma_expressible for s in self.segments)


def flatten(node: Any) -> Flattened:
    """把一棵 component 樹攤平成一個字串 + 段落 + 骨架。"""
    result = Flattened()
    result.skeleton = _walk(node, result, inherited_sigma=True)
    runs = result._runs
    if len(runs) <= 1:
        # **只有一個段落就不插任何標記**——待翻檔是人直接編輯的，每一行都掛一個
        # 無意義的前綴是雜訊，而且很容易被順手刪掉；刪掉之後佔位符驗證會硬失敗，
        # 卻是我們自己造成的。[實測] MP2 的 5,344 棵樹裡 4,871 棵只有一段。
        result.text = runs[0] if runs else ""
    else:
        result.text = "".join(f"[[{n}]]{run}" for n, run in enumerate(runs))
    # 合約對 plain 的定義就是「text 去掉所有 [[n]] 標記」，照著做就好。
    result.plain = _TOKEN.sub("", result.text)
    return result


def _walk(node: Any, out: Flattened, *, inherited_sigma: bool) -> dict[str, Any]:
    """走訪一個節點，回傳它的骨架，並把段落與文字累積進 `out`。"""
    if isinstance(node, str):
        return _emit_string(node, out, style={}, inherited_sigma=inherited_sigma)

    if isinstance(node, list):
        # `["", {...}, {...}]`：第一元素是父級，其餘是 extra。
        parent = node[0] if node else ""
        skeleton = _walk(parent, out, inherited_sigma=inherited_sigma)
        children = [
            _walk(child, out, inherited_sigma=inherited_sigma) for child in node[1:]
        ]
        if children:
            skeleton["extra"] = children
        return skeleton

    if not isinstance(node, dict):
        raise TypeError(f"攤平不了 {type(node).__name__}——component 只會是字串、物件或陣列")

    style = {
        key: value
        for key, value in node.items()
        if key not in _TEXT_KEYS and key not in _STRUCTURE_KEYS
    }
    sigma = inherited_sigma and not (
        _NON_SIGMA_FIELDS & set(style)
        # lang 檔的值裡沒辦法再放一個 translate，所以巢狀 translate 也不行。
        or "translate" in style
        # § 碼只能「開啟」樣式，沒有「關閉」的碼。`italic: false` 是用來壓掉物品名
        # 預設斜體的慣用法——塌縮成 lang 值時那個 false 就沒了，物品名變回斜體。
        or any(value is False for value in style.values())
    )

    if "translate" in node:
        # translate 節點的字面文字是它的 fallback；沒有 fallback 就沒有可翻的字。
        literal = node.get("fallback", "")
        kind = "translate"
    else:
        literal = node.get("text", node.get("", ""))
        kind = "text"

    skeleton = _emit_string(
        literal, out, style=style, inherited_sigma=sigma, node_type=kind
    )

    children = [
        _walk(child, out, inherited_sigma=sigma) for child in node.get("extra", []) or []
    ]
    if children:
        skeleton["extra"] = children
    return skeleton


def _emit_string(
    literal: Any,
    out: Flattened,
    *,
    style: dict[str, Any],
    inherited_sigma: bool,
    node_type: str = "text",
) -> dict[str, Any]:
    """把一段字面文字切成段落並累積起來，回傳這個節點的骨架。

    骨架記的是**這個節點開啟的第一個段落**——`§` 碼在同一個節點裡切出來的後續段落
    沒有各自的骨架節點，重建時由那個節點的 lang 值帶著 § 碼一起長回去。
    """
    text = "" if literal is None else str(literal)
    text = _escape_placeholder_like(text, out)

    runs = _split_by_sigma(text)
    first_index = len(out.segments)

    for offset, (codes, run_text) in enumerate(runs):
        if codes:
            kind = "legacy"
            values: dict[str, Any] = {"codes": codes}
            expressible = inherited_sigma
        elif style:
            kind = "structural"
            values = dict(style)
            expressible = inherited_sigma
        else:
            kind = "none" if offset == 0 else "legacy"
            values = {}
            expressible = inherited_sigma

        out.segments.append(Segment(kind=kind, sigma_expressible=expressible))
        out.styles.append(values)
        out._runs.append(run_text)

    return {"type": node_type, "segment": first_index}


def _split_by_sigma(text: str) -> list[tuple[str, str]]:
    """切成 `(§碼, 這段的文字)`。第一段的 § 碼可能是空的（前導未上色的文字）。"""
    runs: list[tuple[str, str]] = []
    position = 0
    codes = ""
    for match in _SIGMA_RUN.finditer(text):
        chunk = text[position : match.start()]
        # 空的片段不成段：文字以 § 碼開頭時，前面沒有「未上色的那一段」。
        if chunk:
            runs.append((codes, chunk))
        codes = match.group(0)
        position = match.end()
    runs.append((codes, text[position:]))
    return runs


def _escape_placeholder_like(text: str, out: Flattened) -> str:
    """原文含字面 `[[n]]` 時轉義成 `[[\\n]]`，並記下原字串供還原。"""

    def replace(match: re.Match[str]) -> str:
        out.escaped_literals.append(match.group(0))
        return f"[[\\{match.group(1)}]]"

    return _PLACEHOLDER_LIKE.sub(replace, text)
