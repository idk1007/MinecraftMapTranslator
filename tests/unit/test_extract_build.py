# SPDX-License-Identifier: GPL-3.0-or-later
"""`extract/build.py` 的 `plain_string` 覆寫（M13.5）。

`LevelName` 根本不是 component——`sniff()` 只認值的形狀，猜不出「這個欄位不該被
當 JSON 猜」。世界名剛好以 `{`/`"`/`[` 開頭時，`sniff()` 會誤判成 JSON 並嘗試
解析，解析失敗就整個被當成 `unparseable_json` 跳過不翻（一個字都抽不出來，
使用者連在報告裡都看不到這個欄位存在過）。`_consider()` 用
`_PLAIN_STRING_CATEGORIES` 在 `sniff()` 跑完後立刻覆寫掉它的判斷，不等它先跑
一輪再事後修正。

這個檔案沒有走合成 chunk（`test_extract_custom_name.py` 那一套 `RegionBuilder`）
的路，因為要測的欄位住在 `level.dat` 而不是 region——走 `sandbox.import_world` +
`build_units` 讓測試真的穿過 `scan.registry.SOURCES` 那個迴圈（包含新掛上的
`level_dat.scan`），而不是繞過它直接建構節點。
"""

import gzip

import amulet_nbt

from mcmt.extract.build import build_units
from mcmt.safety.paths import ensure_readable
from mcmt.sandbox import import_world


def test_a_level_name_that_looks_like_json_is_not_mistaken_for_one(project) -> None:
    """**這是 `plain_string` 存在的理由。** `LevelName` 根本不是 component，
    但它的值和一行裸字串告示牌長得一模一樣——世界名剛好以 `{` 開頭時，
    `sniff()` 會誤判成 JSON 並嘗試解析，解析失敗就整個被當成
    `unparseable_json` 跳過不翻。這個欄位不該被 sniff() 的 JSON 偵測猜。

    `source` 刻意落在 sandbox 之外（模擬使用者真正的存檔位置）——所以這裡直接寫
    位元組，不走 `write_dat`（它會過 `ensure_writable`，只認 sandbox 底下的路徑）。
    只有 `import_world` 的目標端需要在 sandbox 裡，那由 `import_world` 自己保證。
    """
    source = project / "outside" / "TT_JSON_LOOKING_NAME"
    (source / "region").mkdir(parents=True)
    data = amulet_nbt.CompoundTag(
        {
            "LevelName": amulet_nbt.StringTag("{這不是JSON只是剛好用大括號開頭}"),
            "DataVersion": amulet_nbt.IntTag(4671),
        }
    )
    tag = amulet_nbt.NamedTag(amulet_nbt.CompoundTag({"Data": data}), "")
    payload = tag.save_to(compressed=False)
    (source / "level.dat").write_bytes(gzip.compress(payload))

    imported = import_world(source, name="json_looking_name")
    result = build_units(imported.target, world_root=ensure_readable(imported.target))

    level_name_units = [u for u in result.units if u.category == "level_name"]
    assert len(level_name_units) == 1
    assert level_name_units[0].occurrences[0].encoding == "plain_string"
    assert result.stats["skipped_unparseable"] == 0
