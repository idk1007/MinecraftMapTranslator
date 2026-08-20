# SPDX-License-Identifier: GPL-3.0-or-later
"""resourcepack 後端：把譯文變成 editplan（M10.3）。

後端決定**值是什麼**（這個節點放 `{translate: key}`），寫入層決定**怎麼安全地放進去**
（per-chunk DataVersion 分派、NBT list 同型、外科式重寫、備份與回滾）。分開的理由見
`docs/ownership.md`——最重要的一條是 `editplan.json` 因此成為 `--dry-run` 可以檢查的
中間產物：在不碰存檔的前提下印出「打算改哪些節點、改成什麼」。

三種寫入值：

* `translate` —— 整個節點塌成 `{translate: key}`。只有 `collapsible` 為 true 時合法。
* `component` —— 重建整棵樹，每段填 `<key>.<segment>`。`collapsible` 為 false 時用。
* `literal` —— 直接寫字面字串。給那 4 個 in_place 欄位用（不是 component 的地方）。

**沒被翻的單位不會產生 edit**，而是進 `unwritten` 並帶原因——「還沒翻」與「刻意不翻」
在報告裡要分得開。
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from mcmt.backends.resourcepack.lang import build_lang, sigma_codes_for
from mcmt.extract.placeholders import unescape, validate
from mcmt.model import SCHEMA_VERSION

__all__ = ["PlanResult", "build_editplan"]


@dataclass
class PlanResult:
    document: dict[str, Any]
    lang: dict[str, dict[str, str]] = field(default_factory=dict)
    rejected: list[tuple[str, str]] = field(default_factory=list)


def build_editplan(
    extract: dict[str, Any],
    translations: dict[str, Any],
    *,
    language: str,
) -> PlanResult:
    """把 extract + 譯文合成一份 editplan。**不碰磁碟。**"""
    _check_binding(extract, translations)

    entries = translations["entries"]
    edits: list[dict[str, Any]] = []
    unwritten: list[dict[str, Any]] = []
    lang_pairs: list[tuple[dict[str, Any], str]] = []
    rejected: list[tuple[str, str]] = []

    for unit in extract["units"]:
        unit_id = unit["unit_id"]
        entry = entries.get(unit_id)
        target = (entry or {}).get("target", "")
        status = (entry or {}).get("status")

        if status == "skip":
            unwritten.append({"unit_id": unit_id, "reason": "skipped"})
            continue
        if not target:
            unwritten.append({"unit_id": unit_id, "reason": "untranslated"})
            continue

        check = validate(unit["source"]["text"], target)
        if not check.ok:
            # **hard fail。** 少一個標記就是 § 格式碼染到整行結尾。
            unwritten.append(
                {
                    "unit_id": unit_id,
                    "reason": "placeholder_mismatch",
                    "detail": check.detail or check.reason or "",
                }
            )
            rejected.append((unit_id, check.reason or "placeholder_mismatch"))
            continue

        lang_pairs.append((_lang_view(unit), target))
        for occurrence in unit["occurrences"]:
            if occurrence.get("excluded"):
                # per-occurrence 的排除：同一段原文可能一半可寫一半不可寫。
                continue
            edits.append(_edit_for(unit, occurrence))

    lang = {language: build_lang(lang_pairs)}
    document = {
        "format": "mcmt-editplan",
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "backend": "resourcepack",
        "extract_ref": {
            "extract_fingerprint": extract["world"]["extract_fingerprint"],
            "world_fingerprint": extract["world"]["world_fingerprint"],
        },
        "assets": {
            "resources_zip": "resources.zip",
            "lang_files": {language: f"assets/{extract['project']['namespace']}/lang/{language}.json"},
        },
        "edits": edits,
        "unwritten": unwritten,
    }
    return PlanResult(document=document, lang=lang, rejected=rejected)


def _edit_for(unit: dict[str, Any], occurrence: dict[str, Any]) -> dict[str, Any]:
    return {
        "occurrence_id": occurrence["occurrence_id"],
        "unit_id": unit["unit_id"],
        "container": occurrence["container"],
        "node_path": occurrence["node_path"],
        # 守門用：寫入層會比對節點現在的形狀是不是還是這個。不是就拒寫——
        # 使用者在中間玩過一次遊戲，DataFixer 就可能已經把形狀改掉了（M4-4）。
        "expected_encoding": occurrence["encoding"],
        "value": _value_for(unit, occurrence),
    }


def _value_for(unit: dict[str, Any], occurrence: dict[str, Any]) -> dict[str, Any]:
    if unit["strategy"] == "in_place":
        # 不是 component 的欄位（LevelName、書名、作者、草稿書頁），直接寫字面字串。
        return {"kind": "literal", "text": unescape(unit["source"]["text"]), "style": None}

    if unit["collapsible"]:
        styles = occurrence.get("segment_styles") or [{}]
        return {
            "kind": "translate",
            "key": unit["key"],
            "fallback": None,
            # 單段落時樣式進節點；多段落時樣式已經在 lang 值裡變成 § 碼了。
            "style": _style_for(styles) if len(unit["source"]["segments"]) == 1 else None,
        }

    return {"kind": "component", "tree": _rebuild(unit, occurrence)}


def _style_for(styles: list[dict[str, Any]]) -> dict[str, Any] | None:
    """單段落塌縮時，那一段的樣式要留在節點上。

    寫成 § 碼塞進 lang 值也可以，但留在節點上更接近原本的樣子——原本就是結構化樣式的
    節點，塌縮後仍然是結構化樣式。
    """
    style = {k: v for k, v in (styles[0] or {}).items() if k != "codes"}
    return style or None


def _rebuild(unit: dict[str, Any], occurrence: dict[str, Any]) -> dict[str, Any]:
    """照 `skeleton` 重建整棵樹，每個文字位置填 `<key>.<segment>`。

    **這不是原封搬運。** [實測] 84% 的 extra 子元素自帶格式，重建錯誤的後果是視覺
    損壞而非崩潰——那類錯誤最難自動偵測，所以骨架與樣式都必須照著長回去。
    """
    skeleton = occurrence.get("skeleton") or {"type": "text", "segment": 0}
    styles = occurrence.get("segment_styles") or []
    return _rebuild_node(skeleton, unit["key"], styles)


def _rebuild_node(node: dict[str, Any], key: str, styles: list[dict[str, Any]]) -> dict:
    index = node.get("segment", 0)
    style = dict(styles[index]) if index < len(styles) else {}
    style.pop("codes", None)
    # translate 節點原本的 key 與 fallback 由我們的 key 取代——那正是翻譯的意思。
    style.pop("translate", None)
    style.pop("fallback", None)

    built: dict[str, Any] = {"translate": f"{key}.{index}"}
    built.update(style)
    children = [_rebuild_node(child, key, styles) for child in node.get("extra", [])]
    if children:
        built["extra"] = children
    return built


def _lang_view(unit: dict[str, Any]) -> dict[str, Any]:
    """`build_lang` 要的那幾個欄位。樣式取第一個 occurrence 的。

    同一句話的金色版與紅色版是同一個翻譯單位，但 lang 值只能有一份——所以塌縮時
    用第一個 occurrence 的樣式。這是去重換來的代價，合約把樣式放在 occurrence 層
    就是為了讓這件事看得見。
    """
    first = unit["occurrences"][0]
    return {
        "key": unit["key"],
        "collapsible": unit["collapsible"],
        "segment_count": len(unit["source"]["segments"]),
        "segment_styles": first.get("segment_styles") or [{}],
    }


def _check_binding(extract: dict[str, Any], translations: dict[str, Any]) -> None:
    """譯文必須綁在這一份 extract 上。

    只比對 `world_fingerprint` 是不夠的：同一個世界用新規則集重跑，世界指紋不變而
    unit_id 會變，過期的譯文會通過檢查然後安靜地退化成大量未翻譯。
    """
    if translations["schema_version"] != extract["schema_version"]:
        raise ValueError(
            f"schema 版本不符：extract 是 {extract['schema_version']}，"
            f"譯文是 {translations['schema_version']}。請重新產生。"
        )
    wanted = extract["world"]["extract_fingerprint"]
    found = translations["extract_ref"]["extract_fingerprint"]
    if wanted != found:
        raise ValueError(
            f"這份譯文不是為這份 extract 產生的（{found} ≠ {wanted}）。"
            f"世界或規則集變了就要重新 extract，硬套會安靜地對錯節點。"
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
