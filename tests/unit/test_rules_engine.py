# SPDX-License-Identifier: GPL-3.0-or-later
"""M6 規則引擎的兩條硬性要求（`rules/engine.py`）。

**不動點迭代，上限 32。** 規則會互相餵標籤：一條規則加的標籤讓另一條規則命中，
一路加到沒有新標籤為止。兩條規則互相餵就是無限迴圈，而**靜默停止會產生「有時候
少抽幾個節點」這種最難查的 bug**——所以超限是拋錯，不是回傳現有結果。

**相同輸入的標記結果必須穩定**：規則的套用順序不得影響最終標籤集合。這不是靠自律，
是靠演算法——每一輪都跑完所有規則再取聯集，所以順序本來就進不了結果。
"""

import random

import pytest

from mcmt.errors import RuleEngineDidNotConvergeError
from mcmt.rules.engine import MAX_ITERATIONS, Subject, label


def rule(name, produces, *, when=None):
    """一條測試用規則：`when` 命中時加上 `produces`。"""

    def apply(subject: Subject) -> set[str]:
        if when is None or when in subject.labels:
            return set(produces)
        return set()

    apply.rule_name = name
    return apply


def subject(*labels, keys=()) -> Subject:
    return Subject(key_path=tuple(keys), labels=frozenset(labels))


# --- 基本 -----------------------------------------------------------------


def test_a_rule_adds_its_labels() -> None:
    assert "翻" in label(subject(), [rule("r", {"翻"})])


def test_no_rules_leaves_the_labels_alone() -> None:
    assert label(subject("原有"), []) == frozenset({"原有"})


def test_labels_feed_labels_until_the_fixed_point() -> None:
    """這就是「不動點」的意義：a 觸發 b，b 觸發 c，一輪跑不完。"""
    rules = [
        rule("a", {"b"}, when="a"),
        rule("b", {"c"}, when="b"),
        rule("c", {"d"}, when="c"),
    ]

    assert label(subject("a"), rules) == frozenset({"a", "b", "c", "d"})


def test_the_result_does_not_depend_on_rule_order() -> None:
    """順序影響結果的話，改一次 registry 的排列就會靜默改變抽出來的東西。"""
    rules = [
        rule("a", {"b"}, when="a"),
        rule("b", {"c"}, when="b"),
        rule("c", {"d"}, when="c"),
        rule("x", {"y"}),
    ]
    expected = label(subject("a"), rules)

    for seed in range(8):
        shuffled = rules[:]
        random.Random(seed).shuffle(shuffled)
        assert label(subject("a"), shuffled) == expected


def test_the_same_input_always_gives_the_same_output() -> None:
    rules = [rule("a", {"b", "c"}), rule("b", {"d"}, when="b")]

    assert label(subject("x"), rules) == label(subject("x"), rules)


# --- 收斂 -----------------------------------------------------------------


def test_two_rules_feeding_each_other_forever_raises() -> None:
    """**不可靜默停止。** 靜默停止會產生「有時候少抽幾個節點」這種最難查的 bug。"""
    counter = {"n": 0}

    def endless(subject: Subject) -> set[str]:
        counter["n"] += 1
        return {f"標籤{counter['n']}"}

    endless.rule_name = "永不收斂"

    with pytest.raises(RuleEngineDidNotConvergeError) as exc:
        label(subject(), [endless])

    assert exc.value.iterations == MAX_ITERATIONS


def test_the_error_lists_what_the_last_round_added() -> None:
    """列出最後一輪新增的標籤——那是查「哪兩條規則在互餵」的唯一線索。"""
    step = {"n": 0}

    def endless(subject: Subject) -> set[str]:
        step["n"] += 1
        return {f"第{step['n']}個"}

    endless.rule_name = "永不收斂"

    with pytest.raises(RuleEngineDidNotConvergeError) as exc:
        label(subject(), [endless])

    assert exc.value.added
    assert "永不收斂" in str(exc.value)


def test_a_long_but_finite_chain_still_converges() -> None:
    """31 層還在上限內，不該被誤判成不收斂。"""
    rules = [rule(f"r{i}", {f"L{i + 1}"}, when=f"L{i}") for i in range(MAX_ITERATIONS - 2)]

    result = label(subject("L0"), rules)

    assert f"L{MAX_ITERATIONS - 2}" in result


def test_the_iteration_cap_is_thirty_two() -> None:
    assert MAX_ITERATIONS == 32
