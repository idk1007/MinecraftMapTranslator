# SPDX-License-Identifier: GPL-3.0-or-later
from collections import Counter

import amulet_nbt

from mcmt.model.node import NodePath, key_step
from mcmt.scan.command import scan_command_string


def _path():
    return NodePath([key_step("block_entities"), key_step("Command")])


def test_say_yields_a_bare_string_text_node():
    full = "say Welcome to the arena!"
    stats = Counter()
    nodes = list(
        scan_command_string(
            full,
            base_path=_path(),
            anchor={"kind": "block"},
            stats=stats,
        )
    )
    assert len(nodes) == 1
    node = nodes[0]
    assert node.category == "command_say_text"
    assert isinstance(node.tag, amulet_nbt.StringTag)
    assert str(node.tag) == "Welcome to the arena!"
    # node_path 必須以 decode("command") 收尾，不能停在 base_path 的最後一個
    # key step 上——否則 write 層的 decode-dispatch 認不出它，會落到舊的整值
    # 替換路徑，把 `say ` 前綴一起換掉（寫壞指令）。**要兩個 decode 步驟，不是
    # 一個**：第一個固定是 `(0, len(text))`（跟每個動詞的第一個 decode 步驟一
    # 樣，`write/common.py::_command_length_matches` 依賴這個固定的第一步）；
    # 第二個（最後一個）才是 payload 自己的位置，是真正的 splice 目標。
    decode_steps = [step for step in node.path if step.t == "decode"]
    assert len(decode_steps) == 2
    assert decode_steps[0].codec.value == "command"
    assert decode_steps[0].span == (0, len(full))
    assert decode_steps[1].codec.value == "command"
    span = decode_steps[1].span
    assert span == (len("say "), len(full))
    assert full[span[0] : span[1]] == "Welcome to the arena!"


def test_me_is_treated_the_same_as_say():
    full = "me waves"
    stats = Counter()
    nodes = list(
        scan_command_string(full, base_path=_path(), anchor=None, stats=stats)
    )
    assert nodes[0].category == "command_say_text"
    assert str(nodes[0].tag) == "waves"
    decode_steps = [step for step in nodes[0].path if step.t == "decode"]
    assert len(decode_steps) == 2
    assert decode_steps[0].span == (0, len(full))
    assert decode_steps[1].codec.value == "command"
    span = decode_steps[1].span
    assert span == (len("me "), len(full))
    assert full[span[0] : span[1]] == "waves"


def test_an_unknown_verb_is_skipped_and_counted():
    stats = Counter()
    nodes = list(
        scan_command_string(
            "weather clear", base_path=_path(), anchor=None, stats=stats
        )
    )
    assert nodes == []
    assert stats["skipped_command_unsupported_shape"] == 1


def test_execute_prefix_is_stripped_before_verb_matching():
    full = "execute as @a at @s run say hi there"
    stats = Counter()
    nodes = list(
        scan_command_string(
            full,
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert nodes[0].category == "command_say_text"
    assert str(nodes[0].tag) == "hi there"
    # span 必須換算回**原始** text 的絕對位移，把 execute 剝掉的前綴也算進去
    # ——不能只對剝除後的剩餘字串算 offset。仍然是兩個 decode 步驟：固定的
    # `(0, len(full))` 標記步驟在前，payload 自己的位置在後。
    decode_steps = [step for step in nodes[0].path if step.t == "decode"]
    assert len(decode_steps) == 2
    assert decode_steps[0].span == (0, len(full))
    span = decode_steps[1].span
    assert span == (full.index("hi there"), len(full))
    assert full[span[0] : span[1]] == "hi there"


def test_the_word_run_inside_quotes_does_not_confuse_execute_stripping():
    full = 'execute if block ~ ~ ~ minecraft:stone run say run for it'
    stats = Counter()
    nodes = list(
        scan_command_string(
            full,
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert str(nodes[0].tag) == "run for it"
    decode_steps = [step for step in nodes[0].path if step.t == "decode"]
    assert len(decode_steps) == 2
    assert decode_steps[0].span == (0, len(full))
    span = decode_steps[1].span
    # 這裡的陷阱正是 payload 本身以 "run " 開頭——`full.index("run for it")`
    # 若不小心從頭找可能撞到 execute 前綴裡的那個 "run"，所以改用
    # `rfind` 找**最後**一次出現，確保比對的是 payload 自己那個。
    assert span == (full.rfind("run for it"), len(full))
    assert full[span[0] : span[1]] == "run for it"


def test_tellraw_yields_a_decoded_json_component_node():
    stats = Counter()
    nodes = list(
        scan_command_string(
            'tellraw @a {"text":"Hello"}',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert len(nodes) == 1
    node = nodes[0]
    assert node.category == "command_component_text"
    assert isinstance(node.tag, amulet_nbt.CompoundTag)
    assert str(node.tag["text"]) == "Hello"
    # 最內層 decode 的 span 要對得上原始文字裡那個 JSON 區塊的絕對位移。
    last_span = node.path.last_span
    full = 'tellraw @a {"text":"Hello"}'
    assert full[last_span[0] : last_span[1]] == '{"text":"Hello"}'


def test_a_click_event_pointing_at_another_known_verb_is_skipped():
    stats = Counter()
    nodes = list(
        scan_command_string(
            'tellraw @a {"text":"Click","click_event":'
            '{"action":"run_command","command":"say hi"}}',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert nodes == []
    assert stats["skipped_command_nested_reference"] == 1


def test_a_click_event_pointing_at_an_inert_command_is_not_skipped():
    stats = Counter()
    nodes = list(
        scan_command_string(
            'tellraw @a {"text":"Click","click_event":'
            '{"action":"run_command","command":"/spawn"}}',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert len(nodes) == 1
    assert stats["skipped_command_nested_reference"] == 0


def test_title_subtitle_actionbar_all_work():
    for slot in ("title", "subtitle", "actionbar"):
        stats = Counter()
        nodes = list(
            scan_command_string(
                f'title @a {slot} {{"text":"Hi"}}',
                base_path=_path(),
                anchor=None,
                stats=stats,
            )
        )
        assert len(nodes) == 1, slot


def test_bossbar_name_is_recognised_but_bossbar_value_is_not():
    stats = Counter()
    named = list(
        scan_command_string(
            'bossbar set mymod:bar name {"text":"Boss"}',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert len(named) == 1
    stats2 = Counter()
    valued = list(
        scan_command_string(
            "bossbar set mymod:bar value 50", base_path=_path(), anchor=None, stats=stats2
        )
    )
    assert valued == []


def test_scoreboard_objectives_add_with_and_without_displayname():
    stats = Counter()
    with_name = list(
        scan_command_string(
            'scoreboard objectives add kills dummy {"text":"Kills"}',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert len(with_name) == 1
    stats2 = Counter()
    without_name = list(
        scan_command_string(
            "scoreboard objectives add kills dummy",
            base_path=_path(),
            anchor=None,
            stats=stats2,
        )
    )
    assert without_name == []
    assert stats2["skipped_command_unsupported_shape"] == 0


def test_data_merge_finds_each_message_in_a_native_snbt_list():
    stats = Counter()
    nodes = list(
        scan_command_string(
            'data merge block ~ ~ ~ {front_text:{messages:['
            '{text:"Line 1"},{text:"Line 2"},{text:""},{text:""}]}}',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert len(nodes) == 2  # 空字串沒有可翻文字，見 build.py 的 skipped_empty
    texts = {str(n.tag["text"]) for n in nodes}
    assert texts == {"Line 1", "Line 2"}


def test_data_merge_finds_a_json_string_wrapped_message():
    stats = Counter()
    nodes = list(
        scan_command_string(
            'data merge block ~ ~ ~ {messages:["{\\"text\\":\\"Hello\\"}"]}',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert len(nodes) == 1
    assert str(nodes[0].tag["text"]) == "Hello"


def test_empty_message_increments_skipped_empty_stat():
    stats = Counter()
    nodes = list(
        scan_command_string(
            'data merge block ~ ~ ~ {front_text:{messages:['
            '{text:"Line 1"},{text:""}]}}',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert len(nodes) == 1
    assert stats["skipped_empty"] == 1


def test_native_compound_message_has_two_decode_steps():
    stats = Counter()
    nodes = list(
        scan_command_string(
            'data merge block ~ ~ ~ {front_text:{messages:[{text:"Line 1"}]}}',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert len(nodes) == 1
    decode_steps = [step for step in nodes[0].path if step.t == "decode"]
    assert len(decode_steps) == 2
    assert decode_steps[0].codec.value == "command"
    assert decode_steps[1].codec.value == "snbt"


def test_json_string_wrapped_message_has_three_decode_steps():
    stats = Counter()
    nodes = list(
        scan_command_string(
            'data merge block ~ ~ ~ {messages:["{\\"text\\":\\"Hello\\"}"]}',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert len(nodes) == 1
    decode_steps = [step for step in nodes[0].path if step.t == "decode"]
    assert len(decode_steps) == 3
    assert decode_steps[0].codec.value == "command"
    assert decode_steps[1].codec.value == "snbt"
    assert decode_steps[2].codec.value == "json_component"


def test_data_modify_set_value_is_recognised():
    stats = Counter()
    nodes = list(
        scan_command_string(
            'data modify block ~ ~ ~ front_text.messages[0] merge value {text:"Hi"}',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert len(nodes) == 1


def test_data_merge_entity_text_field_holding_a_translate_component_is_skipped():
    """`data merge entity … {text:{…,translate:"map.key"}}`——`text` 是 text_display
    的**欄位名**，值是一棵指向地圖自己在地化系統的 component。攤平時 `text` 這層
    外殼會把 `translate` 節點藏起來，build.py 的 M13b 守門看不到它，於是這棵樹被
    當成純文字抽出來、`source.text` 變成 Python dict 的字串化。掃描層必須自己擋：
    任何一處有 `translate` 節點就整條跳過，計入 `skipped_already_localised`
    （與 region 路徑 M13b 同一個判準、同一個計數器）。"""
    stats = Counter()
    nodes = list(
        scan_command_string(
            'data merge entity @n[tag=NewsText] '
            '{text:{color:black,translate:"text.iskerside.news1.text"}}',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert nodes == []
    assert stats["skipped_already_localised"] == 1


def test_tellraw_pointing_at_a_map_localisation_key_is_skipped():
    """純 `translate` 參照——沒有字面文字可翻，翻了只會用我們的 key 蓋掉地圖
    原本支援的多語言。掃描層直接擋，不倚賴下游。"""
    stats = Counter()
    nodes = list(
        scan_command_string(
            'tellraw @a {"translate":"text.iskerside.foo","fallback":"News"}',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert nodes == []
    assert stats["skipped_already_localised"] == 1


def test_data_merge_entity_customname_holding_a_translate_component_is_skipped():
    stats = Counter()
    nodes = list(
        scan_command_string(
            'data merge entity @n[tag=X] {CustomName:{translate:"text.iskerside.bar"}}',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert nodes == []
    assert stats["skipped_already_localised"] == 1


def test_a_plain_component_without_translate_still_yields():
    """守門只擋含 `translate` 節點的樹——一般的字面文字 component 不受影響。"""
    stats = Counter()
    nodes = list(
        scan_command_string(
            'data merge entity @n[tag=X] {text:{color:black,text:"Real headline"}}',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert len(nodes) == 1
    assert stats["skipped_already_localised"] == 0


def test_give_finds_the_custom_name_component():
    stats = Counter()
    nodes = list(
        scan_command_string(
            'give @s stone[custom_name={"text":"Special Stone"}]',
            base_path=_path(),
            anchor=None,
            stats=stats,
        )
    )
    assert len(nodes) == 1
    assert str(nodes[0].tag["text"]) == "Special Stone"
