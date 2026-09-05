import pytest
from mcmt.tree.span_locator import (
    LocateError,
    find_balanced_span,
    find_unquoted_token,
    locate_path_span,
)


def test_finds_a_simple_compound():
    text = 'tellraw @a {"text":"Hello"}'
    assert find_balanced_span(text, text.index("{")) == (11, len(text))


def test_ignores_braces_inside_a_json_string_value():
    text = 'tellraw @a {"text":"say {hi}"}'
    start = text.index("{")
    assert find_balanced_span(text, start) == (start, len(text))


def test_ignores_an_escaped_quote_inside_the_string():
    text = r'tellraw @a {"text":"say \"hi\""}'
    start = text.index("{")
    assert find_balanced_span(text, start) == (start, len(text))


def test_handles_single_quoted_snbt_strings():
    text = "data merge block ~ ~ ~ {front_text:{messages:['Line 1']}}"
    start = text.index("{")
    assert find_balanced_span(text, start) == (start, len(text))


def test_a_list_span_is_found_too():
    text = 'give @s stone[custom_name={text:"X"}]'
    start = text.index("[")
    assert find_balanced_span(text, start) == (start, len(text))


def test_raises_when_the_bracket_never_closes():
    text = 'tellraw @a {"text":"Hello"'
    with pytest.raises(LocateError):
        find_balanced_span(text, text.index("{"))


def test_raises_when_start_is_not_an_opener():
    with pytest.raises(LocateError):
        find_balanced_span("hello", 0)


def test_find_unquoted_token_finds_the_run_keyword():
    text = "execute as @a at @s run tellraw @s {\"text\":\"hi\"}"
    idx = find_unquoted_token(text, 0, " run ")
    assert text[idx : idx + 5] == " run "


def test_find_unquoted_token_ignores_the_word_inside_a_json_string():
    text = 'tellraw @a {"text":"run for it"}'
    assert find_unquoted_token(text, 0, " run ") == -1


def test_locate_path_span_on_a_native_compound_list_element():
    text = 'data merge block ~ ~ ~ {front_text:{messages:[{text:"Line 1"},{text:"Line 2"}]}}'
    span = find_balanced_span(text, text.index("{"))
    first = locate_path_span(text, span, ["front_text", "messages", 0])
    second = locate_path_span(text, span, ["front_text", "messages", 1])
    assert text[first[0] : first[1]] == '{text:"Line 1"}'
    assert text[second[0] : second[1]] == '{text:"Line 2"}'
    assert first[0] < second[0]  # Line 2 在 Line 1 右邊——降冪排序時要先處理它


def test_locate_path_span_on_a_string_wrapped_json_element():
    text = 'data merge block ~ ~ ~ {messages:["{\\"text\\":\\"Hello\\"}"]}'
    span = find_balanced_span(text, text.index("{"))
    element = locate_path_span(text, span, ["messages", 0])
    assert text[element[0] : element[1]] == '"{\\"text\\":\\"Hello\\"}"'


def test_locate_path_span_raises_on_a_missing_key():
    text = "{a:1,b:2}"
    span = find_balanced_span(text, 0)
    with pytest.raises(LocateError):
        locate_path_span(text, span, ["c"])
