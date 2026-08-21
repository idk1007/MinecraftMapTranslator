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

from mcmt.model.component import Encoding, sniff
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


def _consider(node, data_version: int, result: ExtractResult):
    """判斷這個節點要不要抽出來，要的話回傳攤平結果。"""
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

    if shape.problem == "unparseable_json":
        # 絕不當裸文字翻掉——翻了會寫回非法 JSON，而遊戲對非法 JSON 的行為未定義。
        result.stats["skipped_unparseable"] += 1
        return None

    if shape.encoding in _LEGACY_JSON and not generation_of(
        data_version
    ).legacy_json_is_content:
        # [遊戲實測 M0-3] 這些在遊戲裡本來就是字面亂碼，不是內容。
        result.stats["skipped_legacy_json_in_native_chunk"] += 1
        return None

    value = shape.parsed if shape.parsed is not None else shape.raw
    if value is None:
        value = node.tag
        if isinstance(value, amulet_nbt.AbstractBaseTag):
            value = _plain(value)

    flattened = flatten(value)
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
