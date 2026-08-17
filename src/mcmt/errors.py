# SPDX-License-Identifier: GPL-3.0-or-later
"""mcmt 的例外階層。

階層見 `docs/superpowers/plans/2026-08-15-mcmt-architecture.md` §1。
這裡只定義**已經有程式碼會拋**的類別——沒人拋的例外類別是文件，不是程式。
"""


class McmtError(Exception):
    """所有 mcmt 例外的根。"""


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


class MissingDependencyError(McmtError):
    """需要一個可選相依，但它沒被安裝。訊息必須告訴使用者裝什麼。"""
