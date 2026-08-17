# SPDX-License-Identifier: GPL-3.0-or-later
"""mcmt 的例外階層。

階層見 `docs/superpowers/plans/2026-08-15-mcmt-architecture.md` §1。
這裡只定義**已經有程式碼會拋**的類別——沒人拋的例外類別是文件，不是程式。
"""


class McmtError(Exception):
    """所有 mcmt 例外的根。"""


class SafetyError(McmtError):
    """有人要碰不該碰的東西。這一族的例外一律中止，沒有 flag 可以關掉。"""


class PathOutsideSandboxError(SafetyError):
    """寫入目標不在 `sandbox/` 底下。"""

    def __init__(self, *, path, sandbox) -> None:
        self.path = path
        self.sandbox = sandbox
        super().__init__(
            f"拒絕寫入 sandbox 之外的路徑：{path}（sandbox 是 {sandbox}）。"
            f"要處理一個世界，先用 `mcmt sandbox import <來源世界>` 把它複製進來。"
        )


class MinecraftSavesPathError(SafetyError):
    """路徑指向 Minecraft 自己的存檔目錄。

    這個檢查**優先於** sandbox 檢查——有人把 `.minecraft` 複製進 sandbox 也一樣擋。
    """

    def __init__(self, *, path) -> None:
        self.path = path
        super().__init__(
            f"拒絕寫入 Minecraft 的存檔目錄：{path}。"
            f"工具永不自動把結果複製回 .minecraft——那是使用者的手動決定。"
        )


class BackupFailedError(SafetyError):
    """備份不成功。**中止**——絕不允許「備份失敗但繼續寫」。"""

    def __init__(self, *, path, directory, detail: str) -> None:
        self.path = path
        self.directory = directory
        self.detail = detail
        super().__init__(
            f"無法備份 {path}：{detail}。已中止，沒有任何檔案被修改。"
            f"（備份目錄：{directory}）"
        )


class BackupRestoreFailedError(SafetyError):
    """回滾時有檔案還原失敗。訊息必須含備份目錄的絕對路徑。

    使用者永遠要有一條救回來的路——即使我們的還原壞了，備份還在那裡。
    """

    def __init__(self, *, directory, failures) -> None:
        self.directory = directory
        self.failures = failures
        listed = "\n".join(f"  {path}：{detail}" for path, detail in failures)
        super().__init__(
            f"回滾失敗，有 {len(failures)} 個檔案沒能還原。\n"
            f"**備份完整地放在這裡，可以手動複製回去：**\n"
            f"  {directory}\n"
            f"沒能還原的檔案：\n{listed}"
        )


class SandboxTargetExistsError(SafetyError):
    """`sandbox import` 的目標已經存在。覆蓋要明講（`--replace`）。"""

    def __init__(self, *, target) -> None:
        self.target = target
        super().__init__(
            f"sandbox 裡已經有 {target}。要覆蓋請加 --replace"
            f"（那會刪掉現有的整份副本，包含你在裡面做過的任何修改）。"
        )


class SandboxTargetInsideSourceError(SafetyError):
    """匯入目標落在來源底下——複製會把自己一直複製進自己。"""

    def __init__(self, *, source, target) -> None:
        self.source = source
        self.target = target
        super().__init__(f"匯入目標 {target} 在來源 {source} 底下，這會無限遞迴。")


class FormatError(McmtError):
    """磁碟上的資料不是我們認得的形狀。"""


class UnknownCompressionError(FormatError):
    """chunk 的壓縮類型位元組不是 1/2/3/4。

    絕不猜測、絕不 fallback 到 zlib——猜錯就是寫壞別人的存檔（CLAUDE.md §1.3）。
    """

    def __init__(self, *, raw_byte: int, type_id: int, chunk_index: int) -> None:
        self.raw_byte = raw_byte
        self.type_id = type_id
        self.chunk_index = chunk_index
        super().__init__(
            f"未知的 chunk 壓縮類型 {type_id}"
            f"（原始位元組 0x{raw_byte:02x}），chunk index {chunk_index}。"
            f"已知類型：1=gzip / 2=zlib / 3=未壓縮 / 4=lz4。"
            f"不猜測、不 fallback——猜錯會寫壞存檔。"
        )


class CorruptCompressedDataError(FormatError):
    """壓縮類型認得，但資料本身解不開。"""

    def __init__(self, *, type_name: str, chunk_index: int, detail: str) -> None:
        self.type_name = type_name
        self.chunk_index = chunk_index
        self.detail = detail
        super().__init__(
            f"chunk index {chunk_index} 的 {type_name} 資料解壓失敗：{detail}"
        )


class TruncatedRegionError(FormatError):
    """region 檔比它自己宣告的短：header 或 payload 跑到檔尾之外。"""

    def __init__(self, *, path, detail: str, chunk_index: int | None = None) -> None:
        self.path = path
        self.chunk_index = chunk_index
        self.detail = detail
        where = "" if chunk_index is None else f"（chunk index {chunk_index}）"
        super().__init__(f"region 檔截斷{where}：{path} — {detail}")


class MalformedRegionError(FormatError):
    """region 的 header 自相矛盾：偏移指進表格、磁區數為 0、長度溢出磁區等。"""

    def __init__(self, *, path, chunk_index: int, detail: str) -> None:
        self.path = path
        self.chunk_index = chunk_index
        self.detail = detail
        super().__init__(
            f"region header 不合法（chunk index {chunk_index}）：{path} — {detail}"
        )


class ExternalChunkError(FormatError):
    """chunk 的內容在外部 `.mcc` 檔。v1 拒絕處理。

    帶 `0x80` 旗標時 region 內只有 header，「原封複製壓縮位元組」複製到的是空的。
    這條寫入路徑在語料 16.2 萬 chunk 裡有 0 個樣本、完全沒測過（CLAUDE.md §1.4）。
    """

    def __init__(self, *, chunk_index: int) -> None:
        self.chunk_index = chunk_index
        super().__init__(
            f"chunk index {chunk_index} 的內容在外部 .mcc 檔（壓縮位元組帶 0x80）。"
            f"v1 拒絕處理——這條寫入路徑沒有任何樣本走過，未測過的寫入路徑比拒絕處理危險。"
        )


class UnsupportedWorldStructureError(FormatError):
    """世界的 chunk 結構不是 1.21 的形狀（多半是 1.12）。v1 拒絕處理整個世界。

    `reason` 是機器可讀的分類，讓 `doctor` 能統計是哪一種症狀：
    `level_wrapper` / `legacy_sign_text` / `missing_data_version`。
    """

    def __init__(self, *, reason: str, chunk_index: int, detail: str) -> None:
        self.reason = reason
        self.chunk_index = chunk_index
        self.detail = detail
        super().__init__(
            f"chunk index {chunk_index} 是不支援的世界結構（{reason}）：{detail}。"
            f"v1 拒絕處理整個世界——1.12 地圖被 1.21 開過之後，同一個世界會同時"
            f"存在兩套 chunk 結構。"
        )


class WorldNotFoundError(McmtError):
    """給定的路徑不存在，或裡面找不到任何 `region` 目錄。"""


class MissingDependencyError(McmtError):
    """需要一個可選相依，但它沒被安裝。訊息必須告訴使用者裝什麼。"""
