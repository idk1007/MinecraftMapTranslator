# SPDX-License-Identifier: GPL-3.0-or-later
"""世界健檢的統計（M1.4）。

`doctor` 回答一個問題：**這個世界能不能被 v1 處理，以及它長什麼樣子。**
輸出同時是 M11 寫入層的規格說明書——它直接告訴你兩套寫入邏輯的實際比例。

**唯讀。** 這個模組不開任何寫入 handle，測試裡有一條比對掃描前後所有檔案的
mtime 與大小，讓「唯讀」不只是一句承諾。

**per-region 串流**：逐 region 檔、逐 chunk 處理，統計只留計數器，峰值記憶體
是單一 chunk。12 萬 chunk 的世界不能整份讀進記憶體。

一個 region 檔的 header 壞掉時，那張 region 會被記錄並中止，掃描繼續往下走——
一個壞檔不該讓整份健檢報告消失。

**放在套件根而不是計畫裡的 `cli/`**：`cli/` 只組裝、不含邏輯（`docs/ownership.md`），
所以統計在這裡，格式化在 `cli/doctor.py`。

**節點形狀分佈**（M1.4 的驗收條件之一）由 M5.6 接上：形狀一律問 `model/component.py`
那個唯一權威，掃描一律走 `scan/sources/` 底下的來源（M13a 起是 `region.py` 與
`entities.py` 兩份）。doctor 自己不判斷任何形狀——它只是把那些模組的答案數起來。

**涵蓋範圍等於 apply 會寫的範圍。** `region/` 與 `entities/` 都要走：doctor 是拒絕
處理的閘門，漏掉一種來源就等於那種來源的 `.mcc` 與不支援結構會通過健檢，然後在
apply 備份之後才炸。`poi/` 不看——那是興趣點索引，沒有任何給人看的字。

**也走 `level.dat`／`data/scoreboard.dat`／`datapacks/**`**（2026-08-31，M13b
最終 review 發現的已知缺口）。這三個來源自己的 `scan()` 已經會吞掉讀不下去的
情況並計數（`skipped_level_dat`／`skipped_scoreboard_dat`／`skipped_datapack_zip`
等）——doctor 之前沒有呼叫它們，所以壞掉的 `level.dat`、損毀的 `scoreboard.dat`、
壞掉的 datapack zip 完全看不見，使用者要跑到 `mcmt extract` 才會發現。這裡直接
重用 `scan/sources/` 的同一份函式（`level_dat.scan`／`scoreboard.scan`／
`datapack.scan`），不是自己另判斷一次——跟 region/entities 那段「問掃描層，就是
extract 問的同一個函式」是同一條理由。**這不是拒絕處理的新閘門**：extract 自己
對這三個來源的壞檔案本來就是「跳過並計數」而不是中止，doctor 只是把這個結果提前
到不用真的跑一次 extract 就看得到，`supported` 的判斷不因此改變。

`legacy_json_in_native_chunk` 這個計數特別重要：它直接告訴使用者「這張地圖有多少
節點我們會跳過不翻」，而那個決定的理由（[遊戲實測 M0-3] 那些節點在遊戲裡本來就是
字面亂碼）不寫在報告上沒人會知道。
"""

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import amulet_nbt

from mcmt.errors import (
    FormatError,
    UnsupportedWorldStructureError,
    WorldNotFoundError,
)
from mcmt.model.component import sniff
from mcmt.model.generation import generation_of
from mcmt.nbtio.region import entities_files, read_region, region_files
from mcmt.nbtio.structure import ensure_supported_structure, load_chunk_root
from mcmt.safety.paths import ensure_readable
from mcmt.world import open_world, region_dirs_of
from mcmt.scan.node import ScannedNode
from mcmt.scan.sources import datapack, level_dat, scoreboard
from mcmt.scan.sources.entities import scan_entities_chunk
from mcmt.scan.sources.region import scan_chunk

__all__ = ["CorruptChunk", "WorldNotFoundError", "WorldSurvey", "survey_world"]


@dataclass(frozen=True)
class CorruptChunk:
    """一個讀不下去的 chunk，或一張讀到一半就中止的 region。"""

    region: str
    chunk_index: int | None
    error: str
    detail: str


@dataclass
class WorldSurvey:
    world: Path
    region_dirs: list[str] = field(default_factory=list)  # 相對於世界根，用於報告
    region_files: int = 0
    entities_files: int = 0
    chunks: int = 0
    entity_chunks: int = 0
    data_versions: Counter = field(default_factory=Counter)
    compression_types: Counter = field(default_factory=Counter)
    external_chunks: int = 0
    unsupported: Counter = field(default_factory=Counter)
    unsupported_examples: dict[str, tuple[str, int]] = field(default_factory=dict)
    corrupt: list[CorruptChunk] = field(default_factory=list)
    text_nodes: int = 0
    node_shapes: Counter = field(default_factory=Counter)
    categories: Counter = field(default_factory=Counter)
    unparseable: int = 0
    legacy_json_in_native_chunk: int = 0
    level_dat_files: int = 0
    scoreboard_dat_files: int = 0
    advancement_files: int = 0
    skipped_level_dat: int = 0
    skipped_scoreboard_dat: int = 0
    skipped_datapack_zip: int = 0
    skipped_advancement_unparseable: int = 0
    skipped_advancement_shape: int = 0

    @property
    def total_chunks(self) -> int:
        """兩種來源加起來。DataVersion 與壓縮類型的直方圖分母是這個，不是 `chunks`
        ——那兩個計數器兩邊都在數，只拿方塊 chunk 當分母會算出超過 100% 的百分比。"""
        return self.chunks + self.entity_chunks

    @property
    def supported(self) -> bool:
        """v1 願不願意處理這個世界。

        外部 `.mcc`、不支援的結構、讀不下去的 chunk——任何一項不是 0 就拒絕整個
        世界。半套支援比拒絕處理危險。
        """
        return not (self.external_chunks or self.unsupported or self.corrupt)


def survey_world(world: Path | str) -> WorldSurvey:
    """掃過世界的每一個 region 檔與實體 region 檔，回傳統計。唯讀。

    **兩種來源都要走，而且理由不只是「統計比較完整」。** `doctor` 是拒絕處理的閘門，
    它的涵蓋範圍必須等於 `apply` 會寫的範圍。M13a 之前它只走 `region_files()`，於是
    `entities/` 裡的外部 `.mcc` 會通過健檢，然後 apply 在**備份之後**才拋
    `ExternalChunkError`、靠 rollback 收場。那個失敗是安全的，但「拒絕處理」的保證
    就不再是保證了。

    形狀分佈同理：extract 掃 `entities/`，doctor 不掃，兩份數字就對不上，而使用者
    看不出那個落差從哪來。
    """
    world = Path(world)
    readable = open_world(world)
    survey = WorldSurvey(world=world, region_dirs=region_dirs_of(readable))
    for path in region_files(readable):
        survey.region_files += 1
        _survey_region(path, survey)
    for path in entities_files(readable):
        survey.entities_files += 1
        _survey_region(path, survey, entities=True)

    stats: Counter = Counter()
    for scanned in level_dat.scan(readable, stats):
        _survey_scanned_node(scanned, survey)
    for scanned in scoreboard.scan(readable, stats):
        _survey_scanned_node(scanned, survey)
    for scanned in datapack.scan(readable, stats):
        _survey_scanned_node(scanned, survey)
    survey.level_dat_files = stats["level_dat_files"]
    survey.scoreboard_dat_files = stats["scoreboard_dat_files"]
    survey.advancement_files = stats["advancement_files"]
    survey.skipped_level_dat = stats["skipped_level_dat"]
    survey.skipped_scoreboard_dat = stats["skipped_scoreboard_dat"]
    survey.skipped_datapack_zip = stats["skipped_datapack_zip"]
    survey.skipped_advancement_unparseable = stats["skipped_advancement_unparseable"]
    survey.skipped_advancement_shape = stats["skipped_advancement_shape"]

    return survey


def _survey_region(path, survey: WorldSurvey, *, entities: bool = False) -> None:
    try:
        for raw in read_region(path):
            if entities:
                survey.entity_chunks += 1
            else:
                survey.chunks += 1
            survey.compression_types[raw.compression_type] += 1
            if raw.is_external:
                survey.external_chunks += 1
                continue
            _survey_chunk(path, raw, survey, entities=entities)
    except FormatError as exc:
        # region header 層級的損壞：這張 region 中止，其餘的繼續掃。
        survey.corrupt.append(
            CorruptChunk(
                region=path.name,
                chunk_index=getattr(exc, "chunk_index", None),
                error=type(exc).__name__,
                detail=str(exc),
            )
        )


def _survey_chunk(path, raw, survey: WorldSurvey, *, entities: bool = False) -> None:
    try:
        root = load_chunk_root(raw)
        data_version = ensure_supported_structure(root, chunk_index=raw.index)
    except UnsupportedWorldStructureError as exc:
        survey.unsupported[exc.reason] += 1
        survey.unsupported_examples.setdefault(exc.reason, (path.name, raw.index))
    except (FormatError, amulet_nbt.NBTLoadError) as exc:
        survey.corrupt.append(
            CorruptChunk(
                region=path.name,
                chunk_index=raw.index,
                error=type(exc).__name__,
                detail=str(exc),
            )
        )
    else:
        survey.data_versions[data_version] += 1
        # 方塊 chunk 的文字在 `block_entities[]`、實體 chunk 的在 `Entities[]`。
        # doctor 不自己走那兩棵樹——它問掃描層，就是 extract 問的同一個函式，
        # 兩份數字才不會漂移。
        source = scan_entities_chunk if entities else scan_chunk
        _survey_text_nodes(source(root), data_version, survey)


_LEGACY_JSON_SHAPES = frozenset(
    {"json_string_object", "json_string_array", "json_string_scalar", "json_empty_quoted"}
)


def _survey_text_nodes(nodes, data_version: int, survey: WorldSurvey) -> None:
    for node in nodes:
        _record_node(node.tag, node.category, data_version, survey)


def _survey_scanned_node(scanned: ScannedNode, survey: WorldSurvey) -> None:
    """`level_dat`／`scoreboard_dat`／`datapack_file` 版本的 `_survey_text_nodes`。

    這三個來源的容器自己帶 `data_version`（`.dat` 有自己的世代；datapack 的
    JSON 檔沒有這回事，容器裡是 `None`——`_record_node` 跟 `extract/build.py`
    的 `_consider()` 一樣，先擋掉 `None` 再問 `generation_of()`，理由同那邊：
    `generation_of(None)` 會直接炸。
    """
    _record_node(
        scanned.node.tag, scanned.node.category, scanned.container.get("data_version"), survey
    )


def _record_node(tag, category: str, data_version: int | None, survey: WorldSurvey) -> None:
    try:
        shape = sniff(tag)
    except TypeError:
        return
    survey.text_nodes += 1
    survey.node_shapes[shape.encoding.value] += 1
    survey.categories[category] += 1
    if shape.problem == "unparseable_json":
        survey.unparseable += 1
    # 「這個世代裡的舊式 JSON 是不是真內容」由 model/generation.py 回答，
    # doctor 不自己記那條分水嶺在哪。
    if (
        data_version is not None
        and not generation_of(data_version).legacy_json_is_content
        and shape.encoding.value in _LEGACY_JSON_SHAPES
    ):
        survey.legacy_json_in_native_chunk += 1
