# SPDX-License-Identifier: GPL-3.0-or-later
"""datapack advancement JSON 的寫入器（M13.7）。

**保證只到「檔案重寫」**——資料夾形式直接覆寫、zip 形式整份重建（既有條目原樣
搬運）。這裡走的是純 Python dict 樹，不透過 amulet_nbt——advancement JSON 本來
就是 JSON，往裡面塞一個 `{"translate": key}` 直接就是最終要 `json.dump` 出去
的東西。
"""

import json
import zipfile
from pathlib import Path

from mcmt.safety.backup import BackupSet
from mcmt.write.common import ApplyOutcome
from mcmt.write.datapack_apply import apply_to_datapack_file


def folder_advancement(world: Path, relative: str, *, title="原標題") -> Path:
    path = world / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"display": {"title": title, "description": "原描述"}, "criteria": {}}),
        encoding="utf-8",
    )
    return path


def edit_for(relative: str, key: str, *, node="title", expected="bare_string"):
    return {
        "occurrence_id": "o:00001",
        "unit_id": "u:advancement_title:aaaaaaaaaaaaaaaa",
        "container": {
            "kind": "datapack_file",
            "path": relative,
            "dimension": None,
            "chunk": None,
            "data_version": None,
            "compression": None,
            "external": False,
        },
        "node_path": [{"t": "key", "name": "display"}, {"t": "key", "name": node}],
        "expected_encoding": expected,
        "value": {"kind": "translate", "key": key, "fallback": "原標題", "style": None},
    }


def literal_edit_for(relative: str, text: str, *, node="title", expected="bare_string", style=None):
    return {
        "occurrence_id": "o:00001",
        "unit_id": "u:advancement_title:aaaaaaaaaaaaaaaa",
        "container": {
            "kind": "datapack_file",
            "path": relative,
            "dimension": None,
            "chunk": None,
            "data_version": None,
            "compression": None,
            "external": False,
        },
        "node_path": [{"t": "key", "name": "display"}, {"t": "key", "name": node}],
        "expected_encoding": expected,
        "value": {"kind": "literal", "text": text, "style": style},
    }


def test_a_folder_advancement_title_becomes_a_translate_component(project) -> None:
    world = project / "sandbox"
    relative = "datapacks/p/data/n/advancement/quest.json"
    path = folder_advancement(world, relative)
    outcome = ApplyOutcome()
    edit = edit_for(relative, "mcmt.advancement_title.bbbbbbbbbbbbbbbb")

    with BackupSet(world) as backup:
        apply_to_datapack_file(world, relative, [edit], outcome, backup)

    document = json.loads(path.read_text("utf-8"))
    assert document["display"]["title"] == {
        "translate": "mcmt.advancement_title.bbbbbbbbbbbbbbbb",
        "fallback": "原標題",
    }
    # 其餘欄位一個字都不動。
    assert document["display"]["description"] == "原描述"
    assert document["criteria"] == {}
    assert outcome.counts["edits_written"] == 1
    assert outcome.counts["files_rewritten"] == 1


def test_a_zip_advancement_is_rewritten_and_other_entries_survive(project) -> None:
    world = project / "sandbox"
    zip_path = world / "datapacks" / "p.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "data/n/advancement/quest.json",
            json.dumps({"display": {"title": "原標題"}}),
        )
        archive.writestr("data/n/function/hello.mcfunction", "say hi")
        archive.writestr("pack.mcmeta", '{"pack":{"pack_format":10}}')

    relative = "datapacks/p.zip/data/n/advancement/quest.json"
    outcome = ApplyOutcome()
    edit = edit_for(relative, "mcmt.advancement_title.cccccccccccccccc")

    with BackupSet(world) as backup:
        apply_to_datapack_file(world, relative, [edit], outcome, backup)

    with zipfile.ZipFile(zip_path) as archive:
        document = json.loads(archive.read("data/n/advancement/quest.json").decode("utf-8"))
        assert document["display"]["title"]["translate"] == "mcmt.advancement_title.cccccccccccccccc"
        assert archive.read("data/n/function/hello.mcfunction").decode() == "say hi"
        assert archive.read("pack.mcmeta").decode() == '{"pack":{"pack_format":10}}'
    assert outcome.counts["edits_written"] == 1


def test_two_files_in_the_same_zip_both_survive_two_separate_calls(project) -> None:
    """**這是 `apply_editplan` 真正會發生的呼叫模式。** `by_file` 按完整的
    `container.path` 分組，zip 裡的 `a.json` 與 `b.json` 是兩個不同的
    `container.path`，天生落進兩個分組——`apply_to_datapack_file` 會被依序呼叫
    兩次，各自對同一個 zip 重讀、重寫。這裡驗的是「即使沒有跨檔案批次，兩次
    呼叫的結果疊得起來，不會有一次把另一次蓋掉」。"""
    world = project / "sandbox"
    zip_path = world / "datapacks" / "p.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("data/n/advancement/a.json", json.dumps({"display": {"title": "A"}}))
        archive.writestr("data/n/advancement/b.json", json.dumps({"display": {"title": "B"}}))

    outcome = ApplyOutcome()
    edit_a = edit_for("datapacks/p.zip/data/n/advancement/a.json", "mcmt.advancement_title.aaaaaaaaaaaaaaaa")
    edit_b = edit_for("datapacks/p.zip/data/n/advancement/b.json", "mcmt.advancement_title.dddddddddddddddd")

    with BackupSet(world) as backup:
        # apply_editplan 對 by_file 的每個分組各呼叫一次——這裡手動模擬那兩次呼叫，
        # relative 兩次都等於各自的 container.path（見函式的說明）。
        apply_to_datapack_file(
            world, "datapacks/p.zip/data/n/advancement/a.json", [edit_a], outcome, backup
        )
        apply_to_datapack_file(
            world, "datapacks/p.zip/data/n/advancement/b.json", [edit_b], outcome, backup
        )

    assert outcome.counts["files_rewritten"] == 2  # 兩次呼叫各自重寫了一次 zip
    assert outcome.counts["edits_written"] == 2
    with zipfile.ZipFile(zip_path) as archive:
        a = json.loads(archive.read("data/n/advancement/a.json").decode())
        b = json.loads(archive.read("data/n/advancement/b.json").decode())
    assert a["display"]["title"]["translate"] == "mcmt.advancement_title.aaaaaaaaaaaaaaaa"
    assert b["display"]["title"]["translate"] == "mcmt.advancement_title.dddddddddddddddd"


def test_a_changed_node_is_refused(project) -> None:
    world = project / "sandbox"
    relative = "datapacks/p/data/n/advancement/quest.json"
    path = folder_advancement(world, relative)
    document = json.loads(path.read_text("utf-8"))
    document["display"]["title"] = {"already": "changed"}
    path.write_text(json.dumps(document), encoding="utf-8")

    outcome = ApplyOutcome()
    edit = edit_for(relative, "mcmt.advancement_title.eeeeeeeeeeeeeeee")

    with BackupSet(world) as backup:
        apply_to_datapack_file(world, relative, [edit], outcome, backup)

    assert outcome.counts["edits_written"] == 0
    assert outcome.unwritten[0]["reason"] == "node_changed"


def test_a_missing_advancement_file_is_refused_without_crashing(project) -> None:
    world = project / "sandbox"
    outcome = ApplyOutcome()
    relative = "datapacks/p/data/n/advancement/gone.json"
    edit = edit_for(relative, "mcmt.advancement_title.ffffffffffffffff")

    with BackupSet(world) as backup:
        apply_to_datapack_file(world, relative, [edit], outcome, backup)

    assert outcome.counts["edits_written"] == 0
    assert outcome.unwritten[0]["reason"] == "node_missing"


def test_a_literal_edit_with_style_keeps_its_style(project) -> None:
    """`_apply_edit_to_json` 的 `literal` 分支必須走 `component_for`，跟
    `translate`/`component` 分支一樣——不能手寫裸字串把 `style` 弄丟。"""
    world = project / "sandbox"
    relative = "datapacks/p/data/n/advancement/quest.json"
    path = folder_advancement(world, relative)
    outcome = ApplyOutcome()
    edit = literal_edit_for(relative, "已改的標題", style={"color": "gold"})

    with BackupSet(world) as backup:
        apply_to_datapack_file(world, relative, [edit], outcome, backup)

    document = json.loads(path.read_text("utf-8"))
    assert document["display"]["title"] == {"text": "已改的標題", "color": "gold"}
    assert outcome.counts["edits_written"] == 1
