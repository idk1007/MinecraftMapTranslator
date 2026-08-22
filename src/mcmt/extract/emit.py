# SPDX-License-Identifier: GPL-3.0-or-later
"""產出 `extract.json` 與**人直接編輯的**待翻檔（M7.3）。

待翻檔的形狀是這次架構調整的重點：每筆自帶 `source`、`note`、`where`，`target` 留空。
人不該為了知道自己在翻什麼而回頭開 `extract.json`（CLAUDE.md 零之二）。

`extract_fingerprint` 是這份 extract 的身分：世界指紋 + 規則集版本 + 命名空間 +
排序過的 unit_id 清單。**同一個世界用不同規則集重跑，world_fingerprint 不變而
unit_id 會變**——只綁世界指紋的話，過期的譯文會通過檢查然後安靜地退化成大量未翻譯。
"""

import json
from datetime import datetime, timezone
from hashlib import blake2b
from typing import Any

from mcmt.extract.build import ExtractResult, Unit
from mcmt.model import SCHEMA_VERSION
from mcmt.model.strategy import strategy_for
from mcmt.width import MEASUREMENT_ID, budget_for, cjk_capacity, enforcement_for, measure

__all__ = [
    "RULE_SET_VERSION",
    "build_extract_document",
    "build_translations_document",
    "dump_json",
]

RULE_SET_VERSION = "1.21.11-r1"
_TOOL_VERSION = "0.1.0.dev0"

# 寬度預算全部來自 `mcmt/width.py`（M8）。這裡刻意**沒有**第二份數字——有兩份就會
# 有一天只校準了其中一份，而寬度錯了的症狀是「譯文在遊戲裡被截掉」，不會有例外
# 也不會有紅字。


def build_extract_document(
    result: ExtractResult,
    *,
    world_name: str,
    world_fingerprint: str,
    level_data_version: int,
    namespace: str,
    target_languages: list[str],
    source_language: str = "en_us",
) -> dict[str, Any]:
    units = [_unit_json(unit) for unit in result.units]
    fingerprint = _extract_fingerprint(
        world_fingerprint, namespace, [u["unit_id"] for u in units]
    )
    return {
        "format": "mcmt-extract",
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "generator": {
            "tool": "mcmt",
            "version": _TOOL_VERSION,
            "rule_set_version": RULE_SET_VERSION,
        },
        "project": {
            "namespace": namespace,
            "source_language": source_language,
            "target_languages": target_languages,
        },
        "world": {
            "name": world_name,
            "level_data_version": level_data_version,
            "world_fingerprint": world_fingerprint,
            "extract_fingerprint": fingerprint,
        },
        "stats": {
            "unit_count": len(units),
            "occurrence_count": result.stats["occurrence_count"],
            "deduped_count": result.stats["deduped_count"],
            "skipped_unparseable": result.stats["skipped_unparseable"],
            "skipped_legacy_json_in_native_chunk": result.stats[
                "skipped_legacy_json_in_native_chunk"
            ],
            "skipped_non_collapsible_in_place": result.stats[
                "skipped_non_collapsible_in_place"
            ],
            "skipped_already_localised": result.stats["skipped_already_localised"],
            # **讀不下去的來源檔也要有數字。** 這幾個計數器原本只活在
            # `result.stats` 裡，沒有任何一條路把它們帶到使用者眼前——一個壞掉
            # 的 `level.dat` 產出的報告和「這個世界沒有東西可翻」一模一樣，那是
            # 靜默失敗。`stats` 的 schema 是 `additionalProperties: true`，加欄位
            # 不動合約。
            "skipped_level_dat": result.stats["skipped_level_dat"],
            "skipped_scoreboard_dat": result.stats["skipped_scoreboard_dat"],
            "skipped_datapack_zip": result.stats["skipped_datapack_zip"],
            "skipped_advancement_unparseable": result.stats[
                "skipped_advancement_unparseable"
            ],
            "skipped_advancement_shape": result.stats["skipped_advancement_shape"],
            "by_category": _by_category(result.units),
        },
        "units": units,
    }


def build_translations_document(
    result: ExtractResult,
    *,
    language: str,
    extract_document: dict[str, Any],
) -> dict[str, Any]:
    """**這是人要打開來編輯的檔案。**"""
    entries = {}
    for unit in result.units:
        entry = {
            "source": unit.text,
            "target": "",
            "note": _note_for(unit),
        }
        where = _where_for(unit)
        if where:
            entry["where"] = where
        entries[unit.unit_id] = entry

    world = extract_document["world"]
    return {
        "format": "mcmt-translations",
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "language": language,
        "extract_ref": {
            "extract_fingerprint": world["extract_fingerprint"],
            "world_fingerprint": world["world_fingerprint"],
            "rule_set_version": RULE_SET_VERSION,
            "unit_count": len(entries),
            "namespace": extract_document["project"]["namespace"],
            "generated_at": extract_document["generated_at"],
        },
        "entries": entries,
        "stats": {
            "total": len(entries),
            "translated": 0,
            "untranslated": len(entries),
            "skipped": 0,
            "rejected": 0,
        },
    }


def dump_json(document: dict[str, Any]) -> str:
    """嚴格 JSON：無註解、無尾逗號、UTF-8、`ensure_ascii=False`。"""
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


# --- 內部 -----------------------------------------------------------------


def _unit_json(unit: Unit) -> dict[str, Any]:
    source: dict[str, Any] = {
        "text": unit.text,
        "plain": unit.plain,
        "segments": unit.segments,
    }
    if unit.escaped_literals:
        source["escaped_literals"] = unit.escaped_literals

    flags = set(unit.flags)
    if unit.escaped_literals:
        flags.add("contains_placeholder_like_text")
    if not unit.collapsible:
        flags.add("non_collapsible_tree")

    strategy = strategy_for(unit.category)
    document = {
        "unit_id": unit.unit_id,
        # in_place 的譯文直接寫進節點，沒有 lang 檔的鍵可放。合約用
        # 「strategy=in_place ⇒ key 必須是 null」把這件事機器強制了。
        "key": unit.key if strategy == "translate_key" else None,
        "category": unit.category,
        "strategy": strategy,
        "collapsible": unit.collapsible,
        "source": source,
        "constraints": _constraints_for(unit),
        "context": _context_for(unit),
        "occurrences": [_occurrence_json(o) for o in unit.occurrences],
    }
    if flags:
        document["flags"] = sorted(flags)
    return document


def _occurrence_json(occurrence) -> dict[str, Any]:
    document = {
        "occurrence_id": occurrence.occurrence_id,
        "container": occurrence.container,
        "anchor": occurrence.anchor,
        "node_path": occurrence.node_path,
        "encoding": occurrence.encoding,
        "segment_styles": occurrence.segment_styles,
        "skeleton": occurrence.skeleton,
        "raw_snapshot": None,
    }
    if occurrence.list_context:
        document["list_context"] = occurrence.list_context
    if occurrence.excluded:
        document["excluded"] = occurrence.excluded
    return document


def _constraints_for(unit: Unit) -> dict[str, Any]:
    budget = budget_for(unit.category)
    return {
        "max_width_px": budget.max_width_px if budget else None,
        "max_lines": budget.max_lines if budget else None,
        "max_chars": cjk_capacity(unit.category),
        "wrap": budget.wrap if budget else "none",
        # **校準完成前一律 warn**（CLAUDE.md C 題）。判準是量測表裡的 `calibrated`
        # 旗標，不是這裡寫死的字串——升級成 error 是資料的決定。
        "enforcement": enforcement_for(unit.category),
        "measurement": MEASUREMENT_ID,
        # 原文本來就放不下是地圖自己的事，但譯者該看得到：他沒有必要塞回一樣長。
        "source_width_px": measure(unit.plain),
    }


def _context_for(unit: Unit) -> dict[str, Any]:
    first = unit.occurrences[0]
    anchor = first.anchor or {}
    position = (
        [anchor["x"], anchor["y"], anchor["z"]]
        if anchor.get("x") is not None
        else None
    )
    return {
        "hint": _hint_for(unit),
        "dimension": first.container.get("dimension"),
        "position": position,
    }


def _hint_for(unit: Unit) -> str:
    """`container.dimension` 只有 region/entities chunk 才有值——`level_dat`
    這類非 chunk 容器（M13.5）合約明講是 `null`（不在任何維度裡），不是漏填。
    **原本這裡把 `None` 直接塞進 `str.join`**：舊範圍下每個來源都是 chunk，
    這個假設從沒被踩過；`level_dat.scan` 掛上後第一個 `level_name` 單位就是
    `TypeError`。沒有維度可講時退回容器種類（`level_dat` 之類）。"""
    count = len(unit.occurrences)
    dimensions = sorted({o.container.get("dimension") for o in unit.occurrences} - {None})
    where = "、".join(dimensions) if dimensions else unit.occurrences[0].container.get("kind", "")
    if count > 1:
        return f"{unit.category}；這段文字在世界裡出現 {count} 次（{where}）"
    return f"{unit.category}（{where}）"


def _note_for(unit: Unit) -> str:
    """給人看的提示。寬度預算要在人開始翻之前就看得到。"""
    bits = [unit.category]
    if strategy_for(unit.category) == "in_place":
        # 這一條沒有 lang 檔那層：譯文直接住在存檔裡，所以一份存檔只有一種語言。
        # 譯者該在動手之前就知道，而不是事後從報告推回來。
        bits.append("寫回節點本身（不經 lang 檔）")
    budget = budget_for(unit.category)
    if budget:
        # **px 對譯者沒有意義，「幾個中文字」有。** 這一句是 M8 存在的理由：
        # 事後才報超寬對人沒有幫助，他得先知道放得下多少才有辦法斟酌用詞。
        capacity = cjk_capacity(unit.category)
        caveat = "" if budget.calibrated else "，未校準僅供參考"
        bits.append(f"寬度上限 {budget.max_width_px}px（約 {capacity} 個中文字{caveat}）")
        width = measure(unit.plain)
        if width > budget.max_width_px:
            bits.append(f"原文本身就超寬 {width}px，不必塞回一樣長")
    if len(unit.occurrences) > 1:
        bits.append(f"出現 {len(unit.occurrences)} 次")
    if len(unit.segments) > 1:
        marks = " ".join(f"[[{i}]]" for i in range(len(unit.segments)))
        bits.append(f"必須保留 {marks}（順序可調）")
    if unit.escaped_literals:
        bits.append("原文含字面 [[n]]，已轉義，請原樣保留")
    if not unit.collapsible:
        bits.append("樣式較複雜，寫回時會逐段重建")
    return "・".join(bits)


def _where_for(unit: Unit) -> str:
    """譯者眼裡「這句話在哪」。**每一筆都要有值**（CLAUDE.md 零之二）。

    `_hint_for` 上面那段自承在這裡原封不動地重演了一次：非 chunk 容器的
    `dimension` 鍵**存在而值是 `None`**，所以 `.get("dimension", "")` 的預設值
    永遠不會生效，`where` 拿到的是 `None`；再加上這些容器的 anchor 沒有座標，
    整個函式回傳 `None`，而 `build_translations_document` 的 `if where:` 把它
    當成假值——`where` 欄位就從 M13b 新加的**每一個** category 的待翻條目裡
    整個消失了。同一個 bug 修了兩次，是因為兩個函式各自從 container 讀
    `dimension`，而「dimension 一定有值」這個假設在舊範圍下從沒被踩過。

    沒有維度也沒有座標時退回**檔案路徑**：`level.dat`、
    `datapacks/x.zip/data/n/advancement/a.json` 對譯者比容器種類具體得多——
    他要找到那句話就是去開那個檔案。連 path 都沒有才退到 kind。
    """
    container = unit.occurrences[0].container
    anchor = unit.occurrences[0].anchor or {}
    dimension = container.get("dimension") or ""
    if anchor.get("x") is None:
        return dimension or container.get("path") or container.get("kind", "")
    return f"{dimension} {anchor['x']},{anchor['y']},{anchor['z']}"


def _by_category(units: list[Unit]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for unit in units:
        counts[unit.category] = counts.get(unit.category, 0) + 1
    return counts


def _extract_fingerprint(
    world_fingerprint: str, namespace: str, unit_ids: list[str]
) -> str:
    digest = blake2b(digest_size=8)
    digest.update(world_fingerprint.encode("utf-8"))
    digest.update(b"\x1f")
    digest.update(RULE_SET_VERSION.encode("utf-8"))
    digest.update(b"\x1f")
    digest.update(namespace.encode("utf-8"))
    for unit_id in sorted(unit_ids):
        digest.update(b"\x1f")
        digest.update(unit_id.encode("utf-8"))
    return f"blake2b:{digest.hexdigest()}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
