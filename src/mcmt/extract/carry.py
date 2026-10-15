# SPDX-License-Identifier: GPL-3.0-or-later
"""重新抽取時沿用舊譯文。

譯文靠編號（`unit_id`）跟原文綁定，編號由原文內容算出來，所以「對得上」的定義
就是編號一樣。這裡刻意**不**做模糊比對：原文改了一個字就是不同的翻譯單位，舊
譯文翻的是舊的那句話，硬套到新的句子上會是悄悄地翻錯。

對不上的舊譯文不丟：列成 `orphans` 讓使用者決定——地圖改了，那幾筆是白翻了，
還是該手動搬去新的條目。
"""

from dataclasses import dataclass, field
from typing import Any

__all__ = ["CarryReport", "Orphan", "carry_translations"]

# 使用者填的欄位。`note`（字寬預算、出現次數）與 `where` 是工具重新算的，
# 不拿舊的蓋過新的。
_USER_FIELDS = ("target", "status")


@dataclass(frozen=True)
class Orphan:
    unit_id: str
    source: str
    target: str
    status: str | None
    where: str | None


@dataclass
class CarryReport:
    carried: int = 0
    orphans: list[Orphan] = field(default_factory=list)
    new_units: int = 0


def carry_translations(old: dict[str, Any], new: dict[str, Any]) -> CarryReport:
    """把 `old` 裡使用者填的 `target`／`status` 依編號搬進 `new`（就地修改）。

    只搬「真的填過」的條目；沒填過的條目消失了不算對不上的譯文，沒有東西白翻。
    搬完重算 `new["stats"]`。"""
    old_entries = old.get("entries", {})
    new_entries = new["entries"]
    report = CarryReport()

    for unit_id, entry in old_entries.items():
        if not (entry.get("target") or entry.get("status")):
            continue
        if unit_id in new_entries:
            for name in _USER_FIELDS:
                if name in entry:
                    new_entries[unit_id][name] = entry[name]
            report.carried += 1
        else:
            report.orphans.append(
                Orphan(
                    unit_id=unit_id,
                    source=str(entry.get("source", "")),
                    target=str(entry.get("target", "")),
                    status=entry.get("status"),
                    where=entry.get("where"),
                )
            )

    report.new_units = sum(1 for unit_id in new_entries if unit_id not in old_entries)
    new["stats"] = _stats(new_entries)
    return report


def _stats(entries: dict[str, Any]) -> dict[str, int]:
    skipped = sum(1 for e in entries.values() if e.get("status") == "skip")
    translated = sum(
        1 for e in entries.values() if e.get("target") and e.get("status") != "skip"
    )
    return {
        "total": len(entries),
        "translated": translated,
        "untranslated": len(entries) - translated - skipped,
        "skipped": skipped,
        "rejected": 0,
    }
