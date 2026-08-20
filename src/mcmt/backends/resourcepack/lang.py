# SPDX-License-Identifier: GPL-3.0-or-later
"""把譯文變成 lang 檔的條目（M10.1）。

`unit.collapsible` 決定寫回方式（CLAUDE.md 三節）：

* `true` → 整棵樹塌成一個 `{translate: key}`，**樣式轉成 § 碼進 lang 值**。
* `false` → 重建整棵樹，**每段一個 key**（`<key>.0`、`<key>.1`…），樣式由樹自己帶。

輸出是嚴格 JSON、鍵排序（diff 穩定）、`ensure_ascii=False`、UTF-8 無 BOM。

**永不覆寫 `minecraft.*`。** 那是原版的命名空間，覆寫會改掉原版所有語言的文字。
"""

import json
from typing import Any, Iterable

from mcmt.extract.placeholders import unescape

__all__ = ["build_lang", "dump_lang", "sigma_codes_for"]

_COLOURS = {
    "black": "0", "dark_blue": "1", "dark_green": "2", "dark_aqua": "3",
    "dark_red": "4", "dark_purple": "5", "gold": "6", "gray": "7",
    "dark_gray": "8", "blue": "9", "green": "a", "aqua": "b",
    "red": "c", "light_purple": "d", "yellow": "e", "white": "f",
}

# 只有「開啟」的方向。§ 沒有關閉某個格式的碼——那正是 `italic: false` 不可塌縮的原因。
_FORMATS = {
    "obfuscated": "k",
    "bold": "l",
    "strikethrough": "m",
    "underlined": "n",
    "italic": "o",
}

_TOKEN = "[["


def sigma_codes_for(style: dict[str, Any]) -> str:
    """把一段的樣式值轉成 § 碼。

    **顏色必須寫在格式之前**：§ 的顏色碼會重設格式，`§l§c文字` 的粗體會被 `§c` 洗掉。
    """
    if "codes" in style:
        return str(style["codes"])  # 本來就是 § 碼的段落，原樣帶過去

    codes = ""
    colour = _COLOURS.get(str(style.get("color", "")))
    if colour:
        codes += f"§{colour}"
    for name, code in _FORMATS.items():
        # 只認 True。False 是「關閉」，§ 表達不了——那種樹不會走到這裡（不可塌縮）。
        if style.get(name) is True:
            codes += f"§{code}"
    return codes


def build_lang(pairs: Iterable[tuple[dict[str, Any], str]]) -> dict[str, str]:
    """`(unit, 譯文) → lang 條目`。空譯文不產生條目。"""
    lang: dict[str, str] = {}
    for unit, target in pairs:
        key = str(unit["key"])
        if key.split(".", 1)[0] == "minecraft":
            raise ValueError(
                f"拒絕寫入 minecraft 命名空間的 key：{key}。"
                f"覆寫原版 key 會改掉原版所有語言的文字。"
            )
        if not target:
            continue  # 尚未翻譯：保留原文，不要寫一個空字串上去

        ordered = _split_by_token(target, unit["segment_count"])
        if unit["collapsible"]:
            # **照譯者寫的順序輸出，不是照段落序號。** 中文語序重排是正常的，
            # 樣式要跟著它那段文字走；照序號重排會把金色套到紅色那段上。
            lang[key] = "".join(
                sigma_codes_for(unit["segment_styles"][index]) + text
                for index, text in ordered
            )
        else:
            # 逐段一個 key，樣式由重建出來的樹自己帶。
            for index, text in ordered:
                lang[f"{key}.{index}"] = text
    return lang


def dump_lang(lang: dict[str, str]) -> str:
    """嚴格 JSON、鍵排序、UTF-8 無 BOM。"""
    return json.dumps(lang, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _split_by_token(target: str, segment_count: int) -> list[tuple[int, str]]:
    """依 `[[n]]` 把譯文切成 `(段落序號, 文字)`，**維持譯文裡的先後順序**。

    順序是譯者決定的，序號只是「這段用哪個樣式」。兩者分開之後，語序重排就不會讓
    樣式跑到別段去。
    """
    _refuse_residue(target, segment_count)
    if segment_count <= 1:
        return [(0, unescape(target))]

    pieces: list[tuple[int, list[str]]] = []
    position = 0
    while position < len(target):
        if target.startswith(_TOKEN, position):
            end = target.find("]]", position)
            body = target[position + 2 : end] if end != -1 else ""
            if end != -1 and body.isdigit():
                index = int(body)
                if index >= segment_count:
                    raise ValueError(
                        f"譯文含 [[{index}]]，但這個單位只有 {segment_count} 段"
                    )
                pieces.append((index, []))
                position = end + 2
                continue
        if not pieces:
            # 第一個標記之前的文字：歸給第 0 段。
            pieces.append((0, []))
        pieces[-1][1].append(target[position])
        position += 1
    return [(index, unescape("".join(chars))) for index, chars in pieces]


def _tokens_in(text: str) -> list[str]:
    found = []
    rest = text
    while _TOKEN in rest:
        start = rest.index(_TOKEN)
        end = rest.find("]]", start)
        if end == -1:
            break
        body = rest[start + 2 : end]
        if body.isdigit():
            found.append(f"[[{body}]]")
        rest = rest[end + 2 :]
    return found


def _refuse_residue(target: str, segment_count: int) -> None:
    """單段落的譯文裡不該有任何標記——有的話代表段落數對不上。

    檢查在**還原轉義之前**做：被轉義的字面文字是使用者看得到的字，不是我們的標記，
    而它在這一刻還帶著反斜線，所以不會被誤判。
    """
    if segment_count > 1:
        return
    residue = _tokens_in(target)
    if residue:
        raise ValueError(
            f"譯文殘留佔位符 {' '.join(residue)}，但這個單位只有一段"
            f"——段落數對不上，寫出去玩家會看到那串記號"
        )
