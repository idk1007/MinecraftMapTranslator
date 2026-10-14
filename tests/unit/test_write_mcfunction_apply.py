# SPDX-License-Identifier: GPL-3.0-or-later
"""`write/mcfunction_apply.py` 的單元測試。

CRLF 保留是這個檔案最重要的一條：`.mcfunction` 逐行處理，換行符全程當不透明
資料，寫回不能把整份 CRLF 檔案改寫成 LF、也不能多插或少插任何一個換行符。
"""

import zipfile

from mcmt.safety.backup import BackupSet
from mcmt.write.common import ApplyOutcome
from mcmt.write.mcfunction_apply import apply_to_mcfunction_file


def _edit(
    container_path: str,
    span: tuple[int, int],
    fallback: str,
    key_suffix: str,
    *,
    line_length: int,
    raw_snapshot: str | None = None,
) -> dict:
    """`container_path` 已經是完整的 `<relative>:<行號 1-based>` 字串。

    **`line_length` 不是可有可無的裝飾。** `scan/command.py` 產出的 decode 鏈
    第一步永遠是 `("command", (0, 整行長度))`（見那裡那段 30 行的說明），而
    `write` 端的長度守門就是靠這個固定第一步判斷「這一行跟 extract 當下是不是
    同一行」。這個 helper 原本只放一個 payload span 的步驟——那不是掃描器真的
    會產出的形狀，於是 2026-09-06 把守門補上時，這些測試會整批被誤判成「檔案
    被改過」。fixture 要長得跟真實產物一樣，不然它保護的是一個不存在的世界。
    """
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
            {"t": "decode", "codec": "command", "arg": None, "span": [0, line_length]},
            {"t": "decode", "codec": "command", "arg": None, "span": list(span)},
        ],
        "expected_encoding": "bare_string",
        "raw_snapshot": raw_snapshot,
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
    edit = _edit(container_path, (4, 9), "你好", "1111111111111111", line_length=9)
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
    edit = _edit(container_path, (4, 9), "hi", "2222222222222222", line_length=9)
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
    edit_a = _edit(container_path, (4, 7), "XXXX", "3333333333333333", line_length=11)
    edit_b = _edit(container_path, (8, 11), "YY", "4444444444444444", line_length=11)
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
    edit = _edit(container_path, (0, 3), "x", "5555555555555555", line_length=17)
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
    edit = _edit(container_path, (0, 3), "x", "6666666666666666", line_length=3)
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
    edit = _edit(container_path, (4, 9), "你好", "7777777777777777", line_length=9)
    outcome = ApplyOutcome()

    with BackupSet(world) as backup:
        apply_to_mcfunction_file(world, container_path, [edit], outcome, backup)

    assert not outcome.unwritten
    with zipfile.ZipFile(zip_path) as archive:
        assert archive.read(entry_name) == "say 你好\r\nsay world\r\n".encode("utf-8")
        assert archive.read(other_name) == b"say untouched\n"
        assert archive.testzip() is None


# --- 延續守門（I2／缺口 C）------------------------------------------------
#
# `write/common.py::_apply_decode_group` 在委派給 `command_span.py` 之前先跑
# `_command_length_matches` ＋ `_decode_command_leaf` ＋ `_guarded_encoding`；
# `.mcfunction` 這條路以前**一道都沒有**。它被記成「重放會靜默寫一次同樣的譯文
# （no-op，無害）」——那個描述只在**檔案沒被改過**時成立。下面幾條把真實行為
# 釘住：長度守門（2026-09-06）與逐位元組守門（2026-10-14）都補上了。


def test_a_line_that_changed_after_extract_is_refused_not_spliced_at_a_stale_offset(
    project,
) -> None:
    """**這是缺口 C 真正危險的樣子，不是 no-op。**

    plan 是照 `tellraw @a {"text":"Hello"}` 抽的；使用者接著自己把那一行改長了。
    沒有守門的話，plan 裡那個**絕對位移**會落在新字串的中間，把指令從一個 token
    的正中央切開，寫出一條語法壞掉的指令——而且 `unwritten` 是空的，報告說一切
    順利：

        tellraw @s {"translate":"mcmt.…","fallback":"Hello"}here, friend","color":"red"}

    長度對不上就是「這一行不是我抽的那一行」，最便宜也最保守的訊號。
    """
    world = project / "sandbox"
    relative = "datapacks/p/data/n/function/hello.mcfunction"
    path = world / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    extracted_line = 'tellraw @a {"text":"Hello"}'
    changed_line = 'tellraw @s {"text":"Hello there, friend","color":"red"}'
    path.write_text(changed_line + "\n", encoding="utf-8")

    container_path = f"{relative}:1"
    edit = _edit(
        container_path,
        (extracted_line.index("{"), len(extracted_line)),
        "你好",
        "9999999999999999",
        line_length=len(extracted_line),
    )
    outcome = ApplyOutcome()

    with BackupSet(world) as backup:
        apply_to_mcfunction_file(world, container_path, [edit], outcome, backup)

    assert [item["reason"] for item in outcome.unwritten] == ["node_changed"]
    # 原檔一個位元都沒被動過，也沒有被算成「重寫過一個檔案」。
    assert path.read_text(encoding="utf-8") == changed_line + "\n"
    assert outcome.counts["files_rewritten"] == 0
    assert outcome.counts["edits_written"] == 0


def test_replaying_the_same_plan_on_an_mcfunction_is_refused(project) -> None:
    """重放同一份 plan：第一次寫進去，第二次被擋下來。

    譯文長度跟原文不同，所以第一次 splice 完這一行的長度就變了——跟 region／
    entities 走 `_apply_decode_group` 的行為對齊（見端到端
    `test_a_translated_region_or_entities_command_edit_is_refused_on_replay`）。
    """
    world = project / "sandbox"
    relative = "datapacks/p/data/n/function/hello.mcfunction"
    path = world / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("say Hello world\n", encoding="utf-8")

    container_path = f"{relative}:1"
    edit = _edit(container_path, (4, 15), "你好世界", "aaaaaaaaaaaaaaaa", line_length=15)

    first = ApplyOutcome()
    with BackupSet(world) as backup:
        apply_to_mcfunction_file(world, container_path, [edit], first, backup)
    assert not first.unwritten
    assert path.read_text(encoding="utf-8") == "say 你好世界\n"

    second = ApplyOutcome()
    with BackupSet(world) as backup:
        apply_to_mcfunction_file(world, container_path, [edit], second, backup)

    assert [item["reason"] for item in second.unwritten] == ["node_changed"]
    assert path.read_text(encoding="utf-8") == "say 你好世界\n"


def test_a_same_length_change_after_extract_is_refused(project) -> None:
    """**缺口 C 的殘餘，2026-10-14 補上。**

    長度守門問的是「這一行還有沒有那麼長」。使用者在 extract 之後把字改成
    **一樣長**的另一句時，長度對得上；這一筆以前照樣寫下去，把使用者自己剛改的
    字蓋掉。現在 `.mcfunction` 跟 region／entities 走同一套守門
    （`write/common.py::guard_command_edits`：長度 → 重新解碼 leaf →
    `_guarded_encoding` 的形狀與 `raw_snapshot` 逐位元組比對）。

    這條測試原本叫 `..._is_the_remaining_mcfunction_gap`，斷言的是「沒被擋下來」。
    當時沒接的理由是 `_decode_command_leaf` 帶著缺口 B；缺口 B 改成掃描端跳過
    之後，三步鏈不再被產生，那個理由不成立了。
    """
    world = project / "sandbox"
    relative = "datapacks/p/data/n/function/hello.mcfunction"
    path = world / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    # extract 當下是 "say Hello world"（15 字元）；使用者改成一樣長的另一句。
    path.write_text("say HELLO WORLD\n", encoding="utf-8")

    container_path = f"{relative}:1"
    edit = _edit(
        container_path,
        (4, 15),
        "你好世界",
        "bbbbbbbbbbbbbbbb",
        line_length=15,
        raw_snapshot="Hello world",
    )
    outcome = ApplyOutcome()

    with BackupSet(world) as backup:
        apply_to_mcfunction_file(world, container_path, [edit], outcome, backup)

    assert [item["reason"] for item in outcome.unwritten] == ["node_changed"]
    assert path.read_text(encoding="utf-8") == "say HELLO WORLD\n"
    assert outcome.counts["files_rewritten"] == 0
    assert outcome.counts["edits_written"] == 0


def test_an_unchanged_line_with_a_matching_snapshot_is_still_written(project) -> None:
    """守門的另一面：`raw_snapshot` 對得上就照常寫。只測拒寫的話，一個什麼都擋
    的守門也會是綠的。"""
    world = project / "sandbox"
    relative = "datapacks/p/data/n/function/hello.mcfunction"
    path = world / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("say Hello world\n", encoding="utf-8")

    container_path = f"{relative}:1"
    edit = _edit(
        container_path,
        (4, 15),
        "你好世界",
        "dddddddddddddddd",
        line_length=15,
        raw_snapshot="Hello world",
    )
    outcome = ApplyOutcome()

    with BackupSet(world) as backup:
        apply_to_mcfunction_file(world, container_path, [edit], outcome, backup)

    assert not outcome.unwritten
    assert path.read_text(encoding="utf-8") == "say 你好世界\n"
    assert outcome.counts["edits_written"] == 1


def test_zip_form_a_same_length_change_is_refused_too(project) -> None:
    """zip 形式與資料夾形式必須是同一條規則——守門只補一邊等於沒補。"""
    world = project / "sandbox"
    zip_relative = "datapacks/p.zip"
    zip_path = world / zip_relative
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    entry_name = "data/n/function/hello.mcfunction"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(entry_name, "say HELLO WORLD\n")

    container_path = f"{zip_relative}/{entry_name}:1"
    edit = _edit(
        container_path,
        (4, 15),
        "你好世界",
        "eeeeeeeeeeeeeeee",
        line_length=15,
        raw_snapshot="Hello world",
    )
    outcome = ApplyOutcome()

    with BackupSet(world) as backup:
        apply_to_mcfunction_file(world, container_path, [edit], outcome, backup)

    assert [item["reason"] for item in outcome.unwritten] == ["node_changed"]
    with zipfile.ZipFile(zip_path) as archive:
        assert archive.read(entry_name) == b"say HELLO WORLD\n"
    assert outcome.counts["files_rewritten"] == 0


def test_zip_form_a_changed_line_is_refused_too(project) -> None:
    """zip 形式與資料夾形式必須是同一條規則——守門只補一邊等於沒補。"""
    world = project / "sandbox"
    zip_relative = "datapacks/p.zip"
    zip_path = world / zip_relative
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    entry_name = "data/n/function/hello.mcfunction"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(entry_name, "say Hello world, and more\n")

    container_path = f"{zip_relative}/{entry_name}:1"
    # plan 是照 15 字元的 "say Hello world" 抽的，磁碟上已經變長了。
    edit = _edit(container_path, (4, 15), "你好世界", "cccccccccccccccc", line_length=15)
    outcome = ApplyOutcome()

    with BackupSet(world) as backup:
        apply_to_mcfunction_file(world, container_path, [edit], outcome, backup)

    assert [item["reason"] for item in outcome.unwritten] == ["node_changed"]
    with zipfile.ZipFile(zip_path) as archive:
        assert archive.read(entry_name) == b"say Hello world, and more\n"
    assert outcome.counts["files_rewritten"] == 0


def test_zip_form_missing_entry_is_refused(project) -> None:
    world = project / "sandbox"
    zip_relative = "datapacks/p.zip"
    zip_path = world / zip_relative
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("data/n/function/other.mcfunction", "say untouched\n")

    entry_name = "data/n/function/missing.mcfunction"
    container_path = f"{zip_relative}/{entry_name}:1"
    edit = _edit(container_path, (0, 3), "x", "8888888888888888", line_length=3)
    outcome = ApplyOutcome()

    with BackupSet(world) as backup:
        apply_to_mcfunction_file(world, container_path, [edit], outcome, backup)

    assert outcome.unwritten[0]["reason"] == "node_missing"
