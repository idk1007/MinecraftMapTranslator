# SPDX-License-Identifier: GPL-3.0-or-later
"""`scan/sources/mcfunction.py`：資料夾／zip 兩種 datapack 形式、CRLF 保留、
行尾延續偵測。"""

import zipfile
from collections import Counter

from mcmt.scan.sources.mcfunction import scan, split_lines


def test_a_folder_datapack_mcfunction_is_scanned(project):
    world = project / "sandbox"
    func = world / "datapacks" / "p" / "data" / "n" / "function" / "hello.mcfunction"
    func.parent.mkdir(parents=True, exist_ok=True)
    func.write_bytes(b'say hello\r\ntellraw @a {"text":"Hi"}\r\n')

    stats = Counter()
    nodes = list(scan(world, stats))

    categories = {n.node.category for n in nodes}
    assert categories == {"command_say_text", "command_component_text"}
    assert all(n.container["kind"] == "datapack_mcfunction_file" for n in nodes)


def test_crlf_is_preserved_byte_for_byte_when_untouched(project):
    # 這條先驗掃描不會意外改到磁碟上的東西（掃描本來就唯讀）；CRLF 保留的
    # 真正回歸測試在 Task 10 的寫入器那邊。
    world = project / "sandbox"
    func = world / "datapacks" / "p" / "data" / "n" / "function" / "hello.mcfunction"
    func.parent.mkdir(parents=True, exist_ok=True)
    original = b"say hello\r\nsay world\r\n"
    func.write_bytes(original)

    list(scan(world, Counter()))

    assert func.read_bytes() == original


def test_a_line_ending_in_backslash_is_skipped_with_its_continuation(project):
    world = project / "sandbox"
    func = world / "datapacks" / "p" / "data" / "n" / "function" / "hello.mcfunction"
    func.parent.mkdir(parents=True, exist_ok=True)
    func.write_bytes(
        b"say normal line\n"
        b"tellraw @a \\\n"
        b'{"text":"continued"}\n'
    )

    stats = Counter()
    nodes = list(scan(world, stats))

    assert len(nodes) == 1  # 只有 "say normal line" 被抽到
    assert nodes[0].node.category == "command_say_text"
    assert stats["skipped_command_line_continuation"] == 2  # 延續行本身 + 它的下一行


def test_a_comment_line_ending_in_backslash_does_not_swallow_the_next_command(project):
    # 迴歸測試（review finding #1）：`# see also \` 這種註解裡剛好有反斜線
    # 結尾，不是 1.20.2+ 的延續語法。它不該觸發延續，更不該把後面那條真的
    # 指令靜默吞掉。
    world = project / "sandbox"
    func = world / "datapacks" / "p" / "data" / "n" / "function" / "hello.mcfunction"
    func.parent.mkdir(parents=True, exist_ok=True)
    func.write_text("# see also \\\nsay hello\n", encoding="utf-8")

    stats = Counter()
    nodes = list(scan(world, stats))

    assert len(nodes) == 1
    assert nodes[0].node.category == "command_say_text"
    assert stats["skipped_command_line_continuation"] == 0


def test_a_real_continuation_followed_by_a_blank_line_is_still_counted(project):
    # review finding #2：延續行的下一行如果剛好是空白／註解（沒有可翻文字），
    # 仍然要算進 skipped_command_line_continuation，不能因為它落進
    # 「非真實行」分支而漏計。
    world = project / "sandbox"
    func = world / "datapacks" / "p" / "data" / "n" / "function" / "hello.mcfunction"
    func.parent.mkdir(parents=True, exist_ok=True)
    func.write_text("tellraw @a \\\n\nsay hello\n", encoding="utf-8")

    stats = Counter()
    nodes = list(scan(world, stats))

    assert len(nodes) == 1
    assert nodes[0].node.category == "command_say_text"
    assert stats["skipped_command_line_continuation"] == 2


def test_container_path_uses_forward_slashes_even_on_windows(project):
    world = project / "sandbox"
    func = world / "datapacks" / "p" / "data" / "n" / "function" / "hello.mcfunction"
    func.parent.mkdir(parents=True, exist_ok=True)
    func.write_text("say hi\n", encoding="utf-8")

    nodes = list(scan(world, Counter()))

    assert "/" in nodes[0].container["path"]
    assert "\\" not in nodes[0].container["path"]
    assert nodes[0].container["path"].endswith("hello.mcfunction:1")


def test_a_zip_datapack_mcfunction_is_scanned(project):
    world = project / "sandbox"
    world.mkdir(parents=True, exist_ok=True)
    (world / "datapacks").mkdir(parents=True, exist_ok=True)
    zip_path = world / "datapacks" / "p.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("pack.mcmeta", "{}")
        archive.writestr("data/n/function/hello.mcfunction", "say hello from zip\n")

    stats = Counter()
    nodes = list(scan(world, stats))

    assert len(nodes) == 1
    assert nodes[0].node.category == "command_say_text"
    assert nodes[0].container["kind"] == "datapack_mcfunction_file"
    assert "hello.mcfunction:1" in nodes[0].container["path"]


def test_blank_lines_and_comment_lines_are_skipped_without_counting(project):
    world = project / "sandbox"
    func = world / "datapacks" / "p" / "data" / "n" / "function" / "hello.mcfunction"
    func.parent.mkdir(parents=True, exist_ok=True)
    func.write_text("# a comment\n\nsay hi\n", encoding="utf-8")

    stats = Counter()
    nodes = list(scan(world, stats))

    assert len(nodes) == 1
    assert stats["skipped_command_line_continuation"] == 0


def test_split_lines_round_trips_crlf_file_byte_for_byte_with_no_edits():
    original = b"say hello\r\nsay world\r\ntrailing no newline"
    text = original.decode("utf-8")

    lines = split_lines(text)
    rejoined = "".join(command + terminator for command, terminator in lines)

    assert rejoined.encode("utf-8") == original


def test_split_lines_only_splits_on_bare_lf_not_other_unicode_breaks():
    text = "a b\n"
    lines = split_lines(text)
    assert lines == [("a b", "\n")]
