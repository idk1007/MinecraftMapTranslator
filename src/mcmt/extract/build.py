# SPDX-License-Identifier: GPL-3.0-or-later
"""把一個世界掃成翻譯單位（M7.3）。

這裡是第一次把前面所有東西接起來：

    region 讀取 → 結構閘門 → 掃描節點 → 形狀嗅探 → denylist → 攤平 → key

每一層的判斷都問它自己的唯一權威，這個模組**不自己判斷任何一件事**——它只負責串
起來、去重、統計。

三條「不翻」的路徑，各自計數並列進報告（CLAUDE.md §二）：

* **denylist 命中** —— 識別碼不是文字，翻了地圖會壞。
* **新世代 chunk 裡的舊式 JSON** —— [遊戲實測 M0-3] 那些字串在遊戲裡本來就是字面
  亂碼，翻了會寫回一個顯示結果同樣是亂碼的字串。計入
  `stats.skipped_legacy_json_in_native_chunk`。
* **JSON 解析失敗** —— 絕不當裸文字翻掉，會寫回非法 JSON。計入
  `stats.skipped_unparseable`。

**去重是 per-unit，排除是 per-occurrence。** 同一段原文可能一半可寫一半不可寫——把
排除做成 per-unit 會讓整個單位被靜默丟掉，那是合約特地加 `occurrence.excluded` 要
擋的事。
"""

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import amulet_nbt

from mcmt.model.component import Encoding, Sniffed, sniff
from mcmt.model.generation import generation_of
from mcmt.model.segments import flatten
from mcmt.model.strategy import IN_PLACE_ENCODINGS, strategy_for
from mcmt.rules.engine import Subject, label
from mcmt.rules.sets.denylist import DENY_LABEL, RULES as DENY_RULES, deny_reason
from mcmt.safety.paths import ReadOnlyPath, ensure_readable
from mcmt.scan.registry import SOURCES
from mcmt.extract.keys import KeyRegistry, translate_key, unit_id

__all__ = ["ExtractResult", "Occurrence", "Unit", "build_units"]

_LEGACY_JSON = {
    Encoding.JSON_STRING_OBJECT,
    Encoding.JSON_STRING_ARRAY,
    Encoding.JSON_STRING_SCALAR,
    Encoding.JSON_EMPTY_QUOTED,
}

# 這幾個欄位的形狀由**欄位**決定，不由值決定——`sniff()` 只認值的形狀，猜不出
# 「這個欄位不該被當 JSON 猜」。世界名剛好以 `{`/`"`/`[` 開頭時，sniff() 會誤判
# 成 JSON 並嘗試解析，解析失敗就整個被當 unparseable_json 跳過不翻。
# `level_dat.py` 是第一個用到這個覆寫的來源；book_title/book_author/
# draft_book_page 目前仍然沿用 sniff() 判成的 bare_string——改變它們的既有行為
# 超出這個任務的範圍，需要自己的一輪（它們的寫入端行為不受影響：
# write/in_place.py 對 bare_string 與 plain_string 是同一個函式 `_bare`）。
#
# **advancement 的兩個欄位是同一件事的第二個實例，但覆寫成的形狀不一樣。**
# datapack 的 `display.title`／`display.description` 的值**直接就是 JSON 型別**
# ——一個 `str` 在那裡的意思永遠是「一個純文字 component」，不存在 NBT 那種
# 「字串內容剛好是一份 JSON 文件」的外層（`scan/sources/datapack.py` 開頭已經
# 說明過這個差異）。所以 sniff() 對它做的 JSON 偵測從頭到尾都是誤判：
#
#   '"Only the brave."'      → json_string_scalar（其實是含引號的字面標題）
#   '[Chapter 1] Beginning'  → json_string_array 解析失敗 → unparseable_json
#
# 前者更糟：datapack 容器的 data_version 是 None（它不是版本化的 NBT），走到
# 下面的舊式 JSON 分支就是 `None < 4325`，**整次 extract 當場 TypeError**。
#
# 但它們覆寫成的是 `bare_string` 而**不是** `plain_string`，這兩者不能混：
#
# * `plain_string` 的意思是「這個欄位根本不是 component」，而合約**用機器強制**
#   了這件事的後果——`extract.schema.json` 有一條 `if/then`：任何一個
#   occurrence 的 encoding 是 `plain_string`，這個 unit 的 strategy 就必須是
#   `in_place`。世界名的確如此（它不吃 translate key）。
# * advancement 的標題**吃 translate key**——原版自己的進度就是這樣做的
#   （`{"translate":"advancements.story.root.title"}`），所以它是 `translate_key`
#   策略，而一個折疊成裸字串的純文字 component 正好就是 `bare_string` 的定義。
#
# 一開始照 `level_name` 的樣子把它們也填 `plain_string`，端到端測試立刻抓到兩件
# 事：extract.json 通不過 schema（`'in_place' was expected`），而且寫入端因為
# 磁碟上是 `bare_string` 而把每一筆 advancement 的 edit 都拒寫成 `node_changed`。
# 形狀覆寫是「這個欄位的值該被當成什麼」，不是「借一個現成的常數來用」。
_FIELD_DETERMINED_ENCODING = {
    "level_name": Encoding.PLAIN_STRING,
    "advancement_title": Encoding.BARE_STRING,
    "advancement_description": Encoding.BARE_STRING,
}


@dataclass
class Occurrence:
    occurrence_id: str
    container: dict[str, Any]
    anchor: dict[str, Any] | None
    node_path: list[dict[str, Any]]
    encoding: str
    segment_styles: list[dict[str, Any]]
    skeleton: dict[str, Any] | None
    list_context: dict[str, Any] | None
    excluded: dict[str, Any] | None = None


@dataclass
class Unit:
    unit_id: str
    key: str
    category: str
    collapsible: bool
    text: str
    plain: str
    segments: list[dict[str, Any]]
    escaped_literals: list[str]
    occurrences: list[Occurrence] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)


@dataclass
class ExtractResult:
    units: list[Unit] = field(default_factory=list)
    keymap: dict[str, Any] = field(default_factory=dict)
    stats: Counter = field(default_factory=Counter)
    denied_reasons: Counter = field(default_factory=Counter)
    chunks: int = 0
    text_nodes: int = 0


def build_units(
    world: Path | str, *, namespace: str = "mcmt", world_root: ReadOnlyPath | None = None
) -> ExtractResult:
    """掃過整個世界，回傳去重後的翻譯單位。唯讀。"""
    readable = world_root or ensure_readable(Path(world))
    result = ExtractResult()
    registry = KeyRegistry()
    by_unit: dict[str, Unit] = {}
    counter = 0

    for source in SOURCES:
        for scanned in source(readable, result.stats):
            node = scanned.node
            result.text_nodes += 1
            built = _consider(node, scanned.container["data_version"], result)
            if built is None:
                continue
            flattened, encoding = built

            discriminator = registry.register(node.category, flattened.text)
            uid = f"u:{node.category}:{discriminator}"
            unit = by_unit.get(uid)
            if unit is None:
                unit = Unit(
                    unit_id=uid,
                    key=translate_key(
                        namespace, node.category, flattened.text,
                        discriminator=discriminator,
                    ),
                    category=node.category,
                    collapsible=flattened.collapsible,
                    text=flattened.text,
                    plain=flattened.plain,
                    segments=[
                        {"kind": s.kind, "sigma_expressible": s.sigma_expressible}
                        for s in flattened.segments
                    ],
                    escaped_literals=list(flattened.escaped_literals),
                    flags=set(registry.flags_for(discriminator)),
                )
                by_unit[uid] = unit
                result.units.append(unit)
            else:
                result.stats["deduped_count"] += 1

            counter += 1
            unit.occurrences.append(
                Occurrence(
                    occurrence_id=f"o:{counter:05d}",
                    container=scanned.container,
                    anchor=node.anchor,
                    node_path=node.path.to_json(),
                    encoding=encoding.value,
                    segment_styles=list(flattened.styles),
                    skeleton=flattened.skeleton,
                    list_context=node.list_context,
                    excluded=_exclusion_for(node.category, encoding),
                )
            )

    result.keymap = registry.keymap()
    result.stats["unit_count"] = len(result.units)
    result.stats["occurrence_count"] = counter
    result.chunks = result.stats["chunks"]
    return result


def _consider(node, data_version: int | None, result: ExtractResult):
    """判斷這個節點要不要抽出來，要的話回傳攤平結果。

    `data_version` 可以是 `None`——不是所有容器都是版本化的 NBT 文件（合約的
    `container.data_version` 型別就是 `["integer","null"]`）。見下面舊式 JSON
    分支的說明。
    """
    keys = tuple(step.name for step in node.path if step.t == "key")
    labels = label(Subject(key_path=keys, value=None), DENY_RULES)
    if DENY_LABEL in labels:
        result.stats["skipped_denylist"] += 1
        result.denied_reasons[deny_reason(labels) or "unknown"] += 1
        return None

    try:
        shape = sniff(node.tag)
    except TypeError:
        result.stats["skipped_not_text"] += 1
        return None

    forced = _FIELD_DETERMINED_ENCODING.get(node.category)
    if forced is not None and isinstance(node.tag, amulet_nbt.StringTag):
        # **不管值長得像不像 JSON，這個欄位的形狀都由欄位決定。** 覆寫掉
        # sniff() 的猜測，而不是先讓它跑一輪再事後修正——跑過再修正的話，值
        # 剛好解析失敗時已經被標成 unparseable_json，圖窮匕見前這個節點就已經
        # 在 _consider() 的下一段被跳過了。
        text = str(node.tag)
        shape = Sniffed(encoding=forced, raw=text, parsed=text)

    if shape.problem == "unparseable_json":
        # 絕不當裸文字翻掉——翻了會寫回非法 JSON，而遊戲對非法 JSON 的行為未定義。
        result.stats["skipped_unparseable"] += 1
        return None

    if (
        data_version is not None
        and shape.encoding in _LEGACY_JSON
        and not generation_of(data_version).legacy_json_is_content
    ):
        # [遊戲實測 M0-3] 這些在遊戲裡本來就是字面亂碼，不是內容。
        #
        # **`data_version is None` 要先擋掉，而且它不只是防禦。** 這條規則問的是
        # 「遊戲會不會替這個節點跑 DataFixerUpper」，而那是**版本化 NBT 文件**才
        # 有的問題。`data_version` 為 None 的容器（datapack 的 JSON 檔）根本不是
        # 版本化文件，沒有 DataFixer 這回事，所以答案不是「跳過」而是「這條規則
        # 不適用」。原本靠的是「呼叫端不會傳 None 進來」這個沒有人強制的隱性約定
        # ——datapack 掃描來源掛上之後它就靜默失效了，症狀是 `generation_of(None)`
        # 在 `None < 4325` 拋 TypeError 並帶走整次 extract。
        result.stats["skipped_legacy_json_in_native_chunk"] += 1
        return None

    value = shape.parsed if shape.parsed is not None else shape.raw
    if value is None:
        value = node.tag
        if isinstance(value, amulet_nbt.AbstractBaseTag):
            value = _plain(value)

    flattened = flatten(value)

    if _contains_translate(flattened.skeleton):
        # 半文字半 key 的樹一樣要擋——重建時會覆蓋掉那個巢狀 key，讓一張支援
        # 多語言的地圖（自己的 translate key + lang 檔）退化成只支援我們寫進去
        # 的那一種。用「任何一處」而不是「根節點是」正是為了這種情況。
        result.stats["skipped_already_localised"] += 1
        return None

    if not flattened.plain.strip():
        result.stats["skipped_empty"] += 1
        return None

    if strategy_for(node.category) == "in_place" and not flattened.collapsible:
        # `in_place` 把譯文直接寫進節點，沒有「每段一個 key」的位置；合約同時要求
        # 「collapsible=false ⇒ translate_key」。兩條規則對這個節點是互斥的，留著
        # 它就會產出一份違反自己合約的 extract.json。跳過並計數，不靜默丟掉。
        result.stats["skipped_non_collapsible_in_place"] += 1
        return None

    return flattened, shape.encoding


def _exclusion_for(category: str, encoding: Encoding) -> dict[str, Any] | None:
    """這個 occurrence 該不該被擋在寫入層之前。

    `in_place` 把譯文直接寫進節點並**保留節點既有的形狀**，所以問題是「這個形狀我們
    有沒有寫過並看過結果」。有依據的清單在 `model/strategy.py`，寫入層的實作與它由
    一個 assert 綁死。

    > **這裡原本是用 `data_version` 近似的**（「舊世代一律排除」），理由是舊世代會
    > 跑 DataFixerUpper、沒有實測依據。[遊戲實測 2026-08-21] 補上依據之後那個近似就
    > 錯了，而且方向很差——它會把已經驗過的形狀一起擋掉，`Arena of Darkness` 的
    > 9,579 個節點就是這樣被擋著的。真正的判準從來不是世代，是形狀。

    未測過的寫入路徑比拒絕處理危險（CLAUDE.md 一之四對 `.mcc` 用的是同一條理由），
    所以擋下來、記原因、進報告。**排除是 per-occurrence 的**：同一段原文有依據的
    那一份照樣寫得出去。
    """
    if strategy_for(category) != "in_place":
        return None
    if encoding.value in IN_PLACE_ENCODINGS:
        return None
    return {
        "reason": "untested_write_shape",
        "detail": (
            f"{category} 的 {encoding.value} 形狀沒有實測依據——"
            f"in_place 保留節點既有的形狀，而這一種從未進遊戲驗過。"
            f"見 SPIKE_RESULT.md 尚待驗證表。"
        ),
    }


def _plain(tag):
    """amulet NBT → 純 Python。攤平器只吃解碼過的結構。"""
    if isinstance(tag, amulet_nbt.StringTag):
        return str(tag)
    if isinstance(tag, amulet_nbt.CompoundTag):
        return {str(k): _plain(v) for k, v in tag.items()}
    if isinstance(tag, amulet_nbt.ListTag):
        return [_plain(v) for v in tag]
    if isinstance(tag, amulet_nbt.ByteTag):
        return bool(int(tag))
    try:
        return int(tag)
    except Exception:
        return str(tag)


def _contains_translate(skeleton: dict[str, Any] | None) -> bool:
    """攤平後的骨架裡任何一處有 `translate` 節點——半文字半 key 的樹也要抓到，
    重建時一樣會覆蓋掉那個巢狀 key。"""
    if not isinstance(skeleton, dict):
        return False
    if skeleton.get("type") == "translate":
        return True
    return any(_contains_translate(child) for child in skeleton.get("extra", []))
