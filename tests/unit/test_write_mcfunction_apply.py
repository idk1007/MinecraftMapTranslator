# SPDX-License-Identifier: GPL-3.0-or-later
"""`write/mcfunction_apply.py` 的單元測試。

CRLF 保留是這個檔案最重要的一條：`.mcfunction` 逐行處理，換行符全程當不透明
資料，寫回不能把整份 CRLF 檔案改寫成 LF、也不能多插或少插任何一個換行符。
"""

import zipfile

from mcmt.safety.backup import BackupSet
from mcmt.write.common import ApplyOutcome
from mcmt.write.mcfunction_apply import apply_to_mcfunction_file


def _edit(container_path: str, span: tuple[int, int], fallback: str, key_suffix: str) -> dict:
    """`container_path` 已經是完整的 `<relative>:<行號 1-based>` 字串。"""
    return {
        "occurrence_id": f"o:{key_suffix}",
        "unit_id": f"u:command_say_text:{key_suffix}",
        "container": {
            "kind": "datapack_mcfunction_file",
            "path": container_path,
            "dimension": None,
            "chunk": None,
            "data_version": None,
            "compression": None,
            "external": False,
        },
        "node_path": [
            {"t": "key", "name": f"__line__{container_path}"},
            {"t": "decode", "codec": "command", "arg": None, "span": list(span)},
        ],
        "expected_encoding": "bare_string",
        "value": {"kind": "literal", "text": fallback, "style": None},
    }


def test_crlf_line_endings_survive_untouched_apply(project) -> None:
    world = project / "sandbox"
    relative = "datapacks/p/data/n/function/hello.mcfunction"
    path = world / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    original = b"say hello\r\nsay world\r\n"
    path.write_bytes(original)

    container_path = f"{relative}:1"
    # 第一行是 "say hello"，"hello" 從位移 4 到 9。
    edit = _edit(container_path, (4, 9), "你好", "1111111111111111")
    outcome = ApplyOutcome()

    with BackupSet(world) as backup:
        apply_to_mcfunction_file(world, container_path, [edit], outcome, backup)

    data = path.read_bytes()
    assert not outcome.unwritten
    assert data == "say 你好\r\nsay world\r\n".encode("utf-8")
    assert data.endswith(b"\r\n")
    assert data.count(b"\r\n") == 2
    assert b"\r\n\r\n" not in data  # 沒有多插入或少插入任何一個換行符


def test_lf_only_file_is_not_turned_into_crlf(project) -> None:
    world = project / "sandbox"
    relative = "datapacks/p/data/n/function/hello.mcfunction"
    path = world / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"say hello\nsay world\n")

    container_path = f"{relative}:1"
    edit = _edit(container_path, (4, 9), "hi", "2222222222222222")
    outcome = ApplyOutcome()

    with BackupSet(world) as backup:
        apply_to_mcfunction_file(world, container_path, [edit], outcome, backup)

    data = path.read_bytes()
    assert data == b"say hi\nsay world\n"
    assert b"\r" not in data


def test_two_edits_on_the_same_line_do_not_collide(project) -> None:
    world = project / "sandbox"
    relative = "datapacks/p/data/n/function/hello.mcfunction"
    path = world / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"say AAA BBB\n")

    container_path = f"{relative}:1"
    # "AAA" 是位移 4..7，"BBB" 是位移 8..11。兩筆各自改一段，順序刻意反著給，
    # 驗證 write 層自己會依 span_order() 由後往前 splice，不依賴呼叫端的順序。
    edit_a = _edit(container_path, (4, 7), "XXXX", "3333333333333333")
    edit_b = _edit(container_path, (8, 11), "YY", "4444444444444444")
    outcome = ApplyOutcome()

    with BackupSet(world) as backup:
        apply_to_mcfunction_file(world, container_path, [edit_b, edit_a], outcome, backup)

    data = path.read_bytes().decode("utf-8")
    assert data == "say XXXX YY\n"
    assert not outcome.unwritten
    assert outcome.counts["edits_written"] == 2
    assert outcome.counts["files_rewritten"] == 1


def test_a_missing_line_is_refused_without_crashing(project) -> None:
    world = project / "sandbox"
    relative = "datapacks/p/data/n/function/hello.mcfunction"
    path = world / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("say only one line\n", encoding="utf-8")

    container_path = f"{relative}:5"
    edit = _edit(container_path, (0, 3), "x", "5555555555555555")
    outcome = ApplyOutcome()

    with BackupSet(world) as backup:
        apply_to_mcfunction_file(world, container_path, [edit], outcome, backup)

    assert outcome.unwritten[0]["reason"] == "node_missing"
    # 原檔沒有被動過。
    assert path.read_text(encoding="utf-8") == "say only one line\n"


def test_a_missing_file_is_refused_without_crashing(project) -> None:
    world = project / "sandbox"
    relative = "datapacks/p/data/n/function/missing.mcfunction"
    container_path = f"{relative}:1"
    edit = _edit(container_path, (0, 3), "x", "6666666666666666")
    outcome = ApplyOutcome()

    with BackupSet(world) as backup:
        apply_to_mcfunction_file(world, container_path, [edit], outcome, backup)

    assert outcome.unwritten[0]["reason"] == "node_missing"


def test_zip_form_applies_edit_and_preserves_other_entries(project) -> None:
    world = project / "sandbox"
    zip_relative = "datapacks/p.zip"
    zip_path = world / zip_relative
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    entry_name = "data/n/function/hello.mcfunction"
    other_name = "data/n/function/other.mcfunction"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(entry_name, "say hello\r\nsay world\r\n")
        archive.writestr(other_name, "say untouched\n")

    container_path = f"{zip_relative}/{entry_name}:1"
    edit = _edit(container_path, (4, 9), "你好", "7777777777777777")
    outcome = ApplyOutcome()

    with BackupSet(world) as backup:
        apply_to_mcfunction_file(world, container_path, [edit], outcome, backup)

    assert not outcome.unwritten
    with zipfile.ZipFile(zip_path) as archive:
        assert archive.read(entry_name) == "say 你好\r\nsay world\r\n".encode("utf-8")
        assert archive.read(other_name) == b"say untouched\n"
        assert archive.testzip() is None


def test_zip_form_missing_entry_is_refused(project) -> None:
    world = project / "sandbox"
    zip_relative = "datapacks/p.zip"
    zip_path = world / zip_relative
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("data/n/function/other.mcfunction", "say untouched\n")

    entry_name = "data/n/function/missing.mcfunction"
    container_path = f"{zip_relative}/{entry_name}:1"
    edit = _edit(container_path, (0, 3), "x", "8888888888888888")
    outcome = ApplyOutcome()

    with BackupSet(world) as backup:
        apply_to_mcfunction_file(world, container_path, [edit], outcome, backup)

    assert outcome.unwritten[0]["reason"] == "node_missing"
