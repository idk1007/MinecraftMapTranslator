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

import pytest

from mcmt.packmeta import FORWARD_PACK_FORMAT
from mcmt.safety.backup import BackupSet
from mcmt.write.common import ApplyOutcome
from mcmt.write.datapack_apply import apply_to_datapack_file


def folder_pack_meta(world: Path, pack_name: str, *, raw=None, pack_format=48) -> Path:
    path = world / "datapacks" / pack_name / "pack.mcmeta"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        raw if raw is not None else json.dumps({"pack": {"pack_format": pack_format}}),
        encoding="utf-8",
    )
    return path


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
        # pack.mcmeta 現在會被加寬 supported_formats（見下方 pack.mcmeta 那組測試），
        # 但宣告的 pack_format 不動。
        pack_meta = json.loads(archive.read("pack.mcmeta"))
        assert pack_meta["pack"]["pack_format"] == 10
        assert pack_meta["pack"]["supported_formats"]["max_inclusive"] == FORWARD_PACK_FORMAT
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


# --- 最終 review：守門、zip 回讀驗證、暫存路徑圍籬 -------------------------


def test_a_plain_string_edit_is_written_against_a_bare_string_on_disk(project) -> None:
    """**Finding 1 第二部分。** `plain_string` 是欄位決定的形狀，`sniff()` 這種
    看值的判斷永遠不會回報它——磁碟上一個裸字串節點永遠是 `bare_string`。守門
    若直接比對字串相等，每一筆 `plain_string` 的 edit 都會被拒寫成
    `node_changed`，不管檔案有沒有真的被改過。這就是 `write/common.py` 在
    commit 18e0c67 修過的同一個 bug；兩個寫入器的守門語意必須一致，否則哪天
    有一個 datapack 來源的 category 走這條路，同一個 bug 會在這裡再爆一次。"""
    world = project / "sandbox"
    relative = "datapacks/p/data/n/advancement/quest.json"
    path = folder_advancement(world, relative)
    outcome = ApplyOutcome()
    edit = literal_edit_for(relative, "譯出來的標題", expected="plain_string")

    with BackupSet(world) as backup:
        apply_to_datapack_file(world, relative, [edit], outcome, backup)

    # 重點是**沒有被拒寫**。寫出去的形狀由 `component_for` 決定（`{"text": …}`，
    # CLAUDE.md「寫入一律用 text 形狀」），那不是這條測試要釘的東西。
    assert outcome.unwritten == []
    assert outcome.counts["edits_written"] == 1
    assert json.loads(path.read_text("utf-8"))["display"]["title"] == {
        "text": "譯出來的標題"
    }


def test_a_genuinely_changed_shape_is_still_refused(project) -> None:
    """橋接只放寬 `bare_string → plain_string` 這一組，不是把守門關掉。"""
    world = project / "sandbox"
    relative = "datapacks/p/data/n/advancement/quest.json"
    path = world / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"display": {"title": {"text": "已經被改成 compound 了"}}}),
        encoding="utf-8",
    )
    outcome = ApplyOutcome()
    edit = literal_edit_for(relative, "譯文", expected="plain_string")

    with BackupSet(world) as backup:
        apply_to_datapack_file(world, relative, [edit], outcome, backup)

    assert outcome.counts["edits_written"] == 0
    assert outcome.unwritten[0]["reason"] == "node_changed"


def _zip_world(project, *, relative="datapacks/p.zip/data/n/advancement/quest.json"):
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
    return world, zip_path, relative


def test_a_corrupt_zip_encode_leaves_the_original_zip_untouched(project, monkeypatch) -> None:
    """**Finding 6。** zip 是這個里程碑裡爆炸半徑最大的一次寫入——一次壞掉毀掉
    的是整份壓縮檔裡的**每一個**條目，不是被改的那一個節點。而它原本是這個檔案
    裡三個寫入器中驗證最弱的一個：`nbtio/datfile.py::write_dat` 有回讀驗證、
    同一個檔案的資料夾路徑也重新 parse 過 JSON，只有 zip 是寫完就直接替換。"""
    from mcmt.errors import DatapackWriteVerificationError
    from mcmt.write import datapack_apply

    world, zip_path, relative = _zip_world(project)
    before = zip_path.read_bytes()
    monkeypatch.setattr(datapack_apply, "_encode_entry", lambda document: b"{ not json")

    outcome = ApplyOutcome()
    edit = edit_for(relative, "mcmt.advancement_title.cccccccccccccccc")

    with pytest.raises(DatapackWriteVerificationError):
        with BackupSet(world) as backup:
            apply_to_datapack_file(world, relative, [edit], outcome, backup)

    assert zip_path.read_bytes() == before
    assert list(zip_path.parent.glob("*.mcmt-tmp")) == []


def test_a_zip_that_fails_its_crc_check_is_refused(project, monkeypatch) -> None:
    """`testzip()` 回傳第一個 CRC 對不上的條目名。真的製造壞 CRC 很難，這裡驗
    的是「這條線真的接上了」——回傳非 None 就必須中止，不是照樣替換。"""
    from mcmt.errors import DatapackWriteVerificationError
    from mcmt.write import datapack_apply

    world, zip_path, relative = _zip_world(project)
    before = zip_path.read_bytes()
    monkeypatch.setattr(
        zipfile.ZipFile, "testzip", lambda self: "data/n/function/hello.mcfunction"
    )

    outcome = ApplyOutcome()
    edit = edit_for(relative, "mcmt.advancement_title.cccccccccccccccc")

    with pytest.raises(DatapackWriteVerificationError):
        with BackupSet(world) as backup:
            apply_to_datapack_file(world, relative, [edit], outcome, backup)

    assert zip_path.read_bytes() == before
    assert list(zip_path.parent.glob("*.mcmt-tmp")) == []


def test_both_temporary_paths_go_through_ensure_writable(project, monkeypatch) -> None:
    """**Finding 7。** `nbtio/datfile.py::write_dat` 立的規矩是**衍生出來的暫存
    路徑要自己再過一次 `ensure_writable`**，不是「父路徑驗過了所以從它衍生的
    東西都安全」——CLAUDE.md 把後者這種隱性推論列為安全關鍵路徑上不接受的。"""
    from mcmt.safety import paths as paths_module
    from mcmt.write import datapack_apply

    seen = []
    real = paths_module.ensure_writable

    def recording(path):
        seen.append(str(path))
        return real(path)

    monkeypatch.setattr(datapack_apply, "ensure_writable", recording)

    world = project / "sandbox"
    relative = "datapacks/p/data/n/advancement/quest.json"
    folder_advancement(world, relative)
    outcome = ApplyOutcome()
    with BackupSet(world) as backup:
        apply_to_datapack_file(
            world, relative, [edit_for(relative, "mcmt.advancement_title.a" * 1)], outcome, backup
        )
    assert any(p.endswith("quest.json.mcmt-tmp") for p in seen), seen

    seen.clear()
    world, zip_path, zip_relative = _zip_world(project)
    outcome = ApplyOutcome()
    with BackupSet(world) as backup:
        apply_to_datapack_file(
            world, zip_relative, [edit_for(zip_relative, "mcmt.advancement_title.b")], outcome, backup
        )
    assert any(p.endswith("p.zip.mcmt-tmp") for p in seen), seen


def test_rewrite_zip_alone_leaves_the_original_untouched(project) -> None:
    """上面那條走完整的 `apply_to_datapack_file`，所以原檔活下來也可能是
    `BackupSet` 還原的功勞。這一條直接呼叫 `_rewrite_zip`，**沒有備份層在旁邊
    接著**——驗的是「替換發生在驗證之後」這個保證本身。"""
    from mcmt.errors import DatapackWriteVerificationError
    from mcmt.safety.paths import ensure_writable
    from mcmt.write.datapack_apply import _rewrite_zip

    world, zip_path, _ = _zip_world(project)
    before = zip_path.read_bytes()

    with zipfile.ZipFile(zip_path) as archive:
        entries = {i.filename: (i, archive.read(i.filename)) for i in archive.infolist()}
    entries["data/n/advancement/quest.json"] = (
        entries["data/n/advancement/quest.json"][0],
        b"{ this is not json",
    )

    with pytest.raises(DatapackWriteVerificationError):
        _rewrite_zip(
            ensure_writable(zip_path),
            entries,
            verify_entry="data/n/advancement/quest.json",
        )

    assert zip_path.read_bytes() == before
    assert list(zip_path.parent.glob("*.mcmt-tmp")) == []


# --- pack.mcmeta 前向加寬：Minecraft 26.2 的教訓移植到 datapack ---------------


def test_a_folder_datapacks_pack_mcmeta_is_widened_when_we_write_into_it(project) -> None:
    """[實測 2026-09-03] 26.2（pack_format 88）拒載 supported_formats 卡在舊值的
    pack；我們寫進 advancement 的譯文會一起失效。寫進資料夾式 datapack 之後就把
    它的 pack.mcmeta 開向未來。"""
    world = project / "sandbox"
    relative = "datapacks/p/data/n/advancement/quest.json"
    folder_advancement(world, relative)
    meta_path = folder_pack_meta(world, "p", pack_format=48)
    outcome = ApplyOutcome()
    edit = edit_for(relative, "mcmt.advancement_title.bbbbbbbbbbbbbbbb")

    with BackupSet(world) as backup:
        apply_to_datapack_file(world, relative, [edit], outcome, backup)

    meta = json.loads(meta_path.read_text("utf-8"))
    assert meta["pack"]["pack_format"] == 48  # 宣告的版本不動
    assert meta["pack"]["supported_formats"] == {
        "min_inclusive": 48,
        "max_inclusive": FORWARD_PACK_FORMAT,
    }
    assert outcome.counts["files_rewritten"] == 2  # advancement JSON + pack.mcmeta
    assert any(w["kind"] == "pack_format_outdated" for w in outcome.warnings)


def test_a_folder_pack_mcmeta_already_forward_is_not_rewritten(project) -> None:
    world = project / "sandbox"
    relative = "datapacks/p/data/n/advancement/quest.json"
    folder_advancement(world, relative)
    raw = json.dumps(
        {
            "pack": {
                "pack_format": 48,
                "supported_formats": {"min_inclusive": 4, "max_inclusive": FORWARD_PACK_FORMAT},
            }
        }
    )
    meta_path = folder_pack_meta(world, "p", raw=raw)
    before = meta_path.read_bytes()
    outcome = ApplyOutcome()
    edit = edit_for(relative, "mcmt.advancement_title.bbbbbbbbbbbbbbbb")

    with BackupSet(world) as backup:
        apply_to_datapack_file(world, relative, [edit], outcome, backup)

    assert meta_path.read_bytes() == before
    assert outcome.counts["files_rewritten"] == 1
    assert not any(w["kind"] == "pack_format_outdated" for w in outcome.warnings)


def test_a_datapack_with_no_pack_mcmeta_is_left_alone(project) -> None:
    world = project / "sandbox"
    relative = "datapacks/p/data/n/advancement/quest.json"
    folder_advancement(world, relative)  # 沒有 pack.mcmeta
    outcome = ApplyOutcome()
    edit = edit_for(relative, "mcmt.advancement_title.bbbbbbbbbbbbbbbb")

    with BackupSet(world) as backup:
        apply_to_datapack_file(world, relative, [edit], outcome, backup)

    assert not (world / "datapacks" / "p" / "pack.mcmeta").exists()
    assert outcome.counts["files_rewritten"] == 1
    assert outcome.counts["edits_written"] == 1


def test_an_unparseable_pack_mcmeta_is_warned_not_aborted(project) -> None:
    """地圖自己的 pack.mcmeta 壞掉不該讓整次翻譯回滾——記一筆警告，繼續。"""
    world = project / "sandbox"
    relative = "datapacks/p/data/n/advancement/quest.json"
    path = folder_advancement(world, relative)
    folder_pack_meta(world, "p", raw="{ 這不是 JSON")
    outcome = ApplyOutcome()
    edit = edit_for(relative, "mcmt.advancement_title.bbbbbbbbbbbbbbbb")

    with BackupSet(world) as backup:
        apply_to_datapack_file(world, relative, [edit], outcome, backup)

    document = json.loads(path.read_text("utf-8"))
    assert document["display"]["title"]["translate"] == "mcmt.advancement_title.bbbbbbbbbbbbbbbb"
    assert (world / "datapacks" / "p" / "pack.mcmeta").read_text("utf-8") == "{ 這不是 JSON"
    assert any(
        w["kind"] == "pack_format_outdated" and "讀不懂" in w["detail"]
        for w in outcome.warnings
    )


def test_pack_mcmeta_is_untouched_when_no_edit_was_written(project) -> None:
    world = project / "sandbox"
    relative = "datapacks/p/data/n/advancement/quest.json"
    folder_advancement(world, relative, title="原標題")
    meta_path = folder_pack_meta(world, "p", pack_format=48)
    before = meta_path.read_bytes()
    outcome = ApplyOutcome()
    # expected_encoding 對不上磁碟上的形狀 → 這筆 edit 會被拒，什麼都沒寫。
    refused = edit_for(relative, "mcmt.x.aaaaaaaaaaaaaaaa", expected="text_compound")

    with BackupSet(world) as backup:
        apply_to_datapack_file(world, relative, [refused], outcome, backup)

    assert meta_path.read_bytes() == before
    assert outcome.counts["files_rewritten"] == 0


def test_a_zip_datapacks_pack_mcmeta_is_widened_too(project) -> None:
    world = project / "sandbox"
    zip_path = world / "datapacks" / "q.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "data/n/advancement/quest.json", json.dumps({"display": {"title": "原標題"}})
        )
        archive.writestr("pack.mcmeta", '{"pack":{"pack_format":26}}')

    relative = "datapacks/q.zip/data/n/advancement/quest.json"
    outcome = ApplyOutcome()
    edit = edit_for(relative, "mcmt.advancement_title.cccccccccccccccc")

    with BackupSet(world) as backup:
        apply_to_datapack_file(world, relative, [edit], outcome, backup)

    with zipfile.ZipFile(zip_path) as archive:
        meta = json.loads(archive.read("pack.mcmeta"))
    assert meta["pack"]["pack_format"] == 26
    assert meta["pack"]["supported_formats"] == {
        "min_inclusive": 26,
        "max_inclusive": FORWARD_PACK_FORMAT,
    }
    assert any(w["kind"] == "pack_format_outdated" for w in outcome.warnings)
