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

節點形狀分佈（M1.4 驗收條件之一）**尚未實作**：那需要 7 種形狀的嗅探器，而
`occurrence.encoding` 的唯一權威只能有一份。等 M5 的 `model/component.py` 出來
之後再接進來，現在另寫一份等於製造兩個會漂移的判斷邏輯。
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
from mcmt.nbtio.region import read_region, region_files
from mcmt.nbtio.structure import ensure_supported_structure, load_chunk_root
from mcmt.safety.paths import ensure_readable

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
    chunks: int = 0
    data_versions: Counter = field(default_factory=Counter)
    compression_types: Counter = field(default_factory=Counter)
    external_chunks: int = 0
    unsupported: Counter = field(default_factory=Counter)
    unsupported_examples: dict[str, tuple[str, int]] = field(default_factory=dict)
    corrupt: list[CorruptChunk] = field(default_factory=list)

    @property
    def supported(self) -> bool:
        """v1 願不願意處理這個世界。

        外部 `.mcc`、不支援的結構、讀不下去的 chunk——任何一項不是 0 就拒絕整個
        世界。半套支援比拒絕處理危險。
        """
        return not (self.external_chunks or self.unsupported or self.corrupt)


def survey_world(world: Path | str) -> WorldSurvey:
    """掃過世界的每一個 region 檔，回傳統計。唯讀。"""
    world = Path(world)
    if not world.is_dir():
        raise WorldNotFoundError(f"找不到世界資料夾：{world}")

    readable = ensure_readable(world)
    region_dirs = sorted(
        d.relative_to(readable) for d in readable.rglob("region") if d.is_dir()
    )
    if not region_dirs:
        raise WorldNotFoundError(
            f"{world} 底下找不到任何 region 目錄——這看起來不是一個世界資料夾"
        )

    survey = WorldSurvey(world=world, region_dirs=region_dirs)
    for path in region_files(readable):
        survey.region_files += 1
        _survey_region(path, survey)
    return survey


def _survey_region(path, survey: WorldSurvey) -> None:
    try:
        for raw in read_region(path):
            survey.chunks += 1
            survey.compression_types[raw.compression_type] += 1
            if raw.is_external:
                survey.external_chunks += 1
                continue
            _survey_chunk(path, raw, survey)
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


def _survey_chunk(path, raw, survey: WorldSurvey) -> None:
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
