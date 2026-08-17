# SPDX-License-Identifier: GPL-3.0-or-later
"""M3.2 `.dat` 檔的讀寫（`level.dat`）。

和 region 不同，`level.dat` **沒有**「未修改的部分原封搬運」這種粒度——它是一份
NBT 文件，改一個欄位就得整份重新編碼。所以這裡的保證只到 L1（NBT 再序列化位元組
一致），而不是 region 的 L3（根本不解碼）。

`level.dat` 是 `LevelName` 這個 in_place 欄位的所在地（CLAUDE.md「4 個 in_place
欄位」），M11 會用到。
"""

import gzip
import zlib

import amulet_nbt
import pytest

from mcmt.errors import DatFormatError, PathOutsideSandboxError
from mcmt.nbtio.datfile import DatFile, read_dat, write_dat
from mcmt.safety.paths import ensure_readable


def sample_tag(name: str = "TT_WORLD") -> amulet_nbt.NamedTag:
    data = amulet_nbt.CompoundTag()
    data["LevelName"] = amulet_nbt.StringTag(name)
    data["DataVersion"] = amulet_nbt.IntTag(4671)
    root = amulet_nbt.CompoundTag()
    root["Data"] = data
    return amulet_nbt.NamedTag(root, "")


def write_source(directory, tag: amulet_nbt.NamedTag, *, form: str = "gzip"):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "level.dat"
    payload = tag.save_to(compressed=False)
    if form == "gzip":
        path.write_bytes(gzip.compress(payload))
    elif form == "zlib":
        path.write_bytes(zlib.compress(payload))
    else:
        path.write_bytes(payload)
    return path


# --- 讀 -------------------------------------------------------------------


def test_a_gzipped_dat_is_read(project) -> None:
    path = write_source(project / "saves", sample_tag())

    dat = read_dat(ensure_readable(path))

    assert str(dat.tag.compound["Data"]["LevelName"]) == "TT_WORLD"
    assert dat.compression == "gzip"


@pytest.mark.parametrize("form", ["gzip", "zlib", "none"])
def test_the_compression_form_is_detected(project, form: str) -> None:
    path = write_source(project / "saves", sample_tag(), form=form)

    assert read_dat(ensure_readable(path)).compression == form


def test_reading_refuses_a_raw_path(project) -> None:
    path = write_source(project / "saves", sample_tag())

    with pytest.raises(TypeError) as exc:
        read_dat(path)
    assert "ensure_readable" in str(exc.value)


def test_something_that_is_not_nbt_is_refused(project) -> None:
    directory = project / "saves"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "level.dat"
    path.write_bytes(b"definitely not nbt")

    with pytest.raises(DatFormatError):
        read_dat(ensure_readable(path))


# --- 寫 -------------------------------------------------------------------


def test_a_dat_round_trips(project) -> None:
    source = write_source(project / "saves", sample_tag())
    dat = read_dat(ensure_readable(source))
    target = project / "sandbox" / "level.dat"

    write_dat(target, dat)

    assert read_dat(ensure_readable(target)).tag.compound == dat.tag.compound


def test_the_nbt_payload_survives_a_round_trip_byte_for_byte(project) -> None:
    """L1：amulet-nbt 解析→序列化必須還原同樣的位元組。"""
    source = write_source(project / "saves", sample_tag())
    payload_before = gzip.decompress(source.read_bytes())
    target = project / "sandbox" / "level.dat"

    write_dat(target, read_dat(ensure_readable(source)))

    assert gzip.decompress(target.read_bytes()) == payload_before


@pytest.mark.parametrize("form", ["gzip", "zlib", "none"])
def test_the_original_compression_form_is_written_back(project, form: str) -> None:
    """讀什麼形式就寫回什麼形式——不順手「升級」成 gzip。"""
    source = write_source(project / "saves", sample_tag(), form=form)
    target = project / "sandbox" / "level.dat"

    write_dat(target, read_dat(ensure_readable(source)))

    assert read_dat(ensure_readable(target)).compression == form


def test_writing_the_same_dat_twice_gives_the_same_bytes(project) -> None:
    """gzip 標頭預設會塞入當下時間，那會讓輸出每次都不一樣。"""
    source = write_source(project / "saves", sample_tag())
    dat = read_dat(ensure_readable(source))
    first = project / "sandbox" / "a.dat"
    second = project / "sandbox" / "b.dat"

    write_dat(first, dat)
    write_dat(second, dat)

    assert first.read_bytes() == second.read_bytes()


def test_writing_outside_the_sandbox_is_refused(project) -> None:
    with pytest.raises(PathOutsideSandboxError):
        write_dat(project / "escaped.dat", DatFile(tag=sample_tag(), compression="gzip"))


def test_a_failed_write_leaves_the_original_intact(project, monkeypatch) -> None:
    import os

    target = project / "sandbox" / "level.dat"
    write_dat(target, DatFile(tag=sample_tag("first"), compression="gzip"))
    before = target.read_bytes()

    def explode(*args, **kwargs):
        raise OSError("模擬寫入失敗")

    monkeypatch.setattr(os, "replace", explode)

    with pytest.raises(OSError):
        write_dat(target, DatFile(tag=sample_tag("second"), compression="gzip"))

    assert target.read_bytes() == before
    assert list(target.parent.glob("*.mcmt-tmp")) == []
