# SPDX-License-Identifier: GPL-3.0-or-later
"""不動點迭代（M6）。

規則會互相餵標籤：一條規則加的標籤讓另一條規則命中，一路加到沒有新標籤為止。

**兩條硬性要求：**

1. **上限 32 輪，超限拋錯。** 兩條規則互相餵就是無限迴圈，而靜默停止會產生「有時候
   少抽幾個節點」這種最難查的 bug——同一個世界跑兩次結果不同，卻沒有任何跡象。
2. **順序不得影響結果。** 這不是靠自律：每一輪跑完**所有**規則再取聯集，所以規則的
   排列本來就進不了結果。規則只加標籤、不刪標籤，也是為了這個。
"""

from dataclasses import dataclass
from typing import Callable, Iterable

from mcmt.errors import RuleEngineDidNotConvergeError

__all__ = ["MAX_ITERATIONS", "Rule", "Subject", "label"]

MAX_ITERATIONS = 32

Rule = Callable[["Subject"], set[str]]


@dataclass(frozen=True)
class Subject:
    """規則要判斷的東西。

    `key_path` 是從 chunk 根走到這個節點的**鍵名序列**，索引已經拿掉——denylist 關心
    的是「這是不是 palette 底下的 Name」，不是「第幾個 palette」。
    """

    key_path: tuple[str, ...] = ()
    labels: frozenset[str] = frozenset()
    value: str | None = None

    def with_labels(self, labels: frozenset[str]) -> "Subject":
        return Subject(key_path=self.key_path, labels=labels, value=self.value)


def label(subject: Subject, rules: Iterable[Rule]) -> frozenset[str]:
    """反覆套用規則直到收斂，回傳最終的標籤集合。"""
    rules = list(rules)
    labels = subject.labels

    for iteration in range(1, MAX_ITERATIONS + 1):
        added: dict[str, set[str]] = {}
        current = subject.with_labels(labels)
        for rule in rules:
            produced = set(rule(current)) - labels
            if produced:
                added[_name_of(rule)] = produced
        if not added:
            return labels
        labels = labels | {name for produced in added.values() for name in produced}

    raise RuleEngineDidNotConvergeError(iterations=MAX_ITERATIONS, added=added)


def _name_of(rule: Rule) -> str:
    return getattr(rule, "rule_name", getattr(rule, "__name__", repr(rule)))
