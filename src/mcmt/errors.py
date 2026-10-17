# SPDX-License-Identifier: GPL-3.0-or-later
"""mcmt 的例外階層。

階層見 `docs/superpowers/plans/2026-08-15-mcmt-architecture.md` §1。
這裡只定義**已經有程式碼會拋**的類別——沒人拋的例外類別是文件，不是程式。

**每個例外是「標題＋內容」**：`title` 是類別屬性（給對話框的標題列、終端機的
`【標題】`），`str(exc)` 是內容。措辭的來源是 `docs/error-messages-review.md`；
「標題不超過 8 個字、內容 1～2 行、『未變更任何檔案』只在真的沒改任何東西的中止
情境出現」是那份文件的原則，這裡照做。
"""

from pathlib import Path


class McmtError(Exception):
    """所有 mcmt 例外的根。"""

    title = "發生錯誤"


class SafetyError(McmtError):
    """有人要碰不該碰的東西。這一族的例外一律中止，沒有 flag 可以關掉。"""

    title = "已中止"


_WAYS_IN = "請先匯入沙盒（mcmt sandbox import），或直接把地圖拖曳至程式。"


class PathOutsideSandboxError(SafetyError):
    """寫入目標不在 `sandbox/` 底下。"""

    title = "只能修改沙盒"

    def __init__(self, *, path, sandbox) -> None:
        self.path = path
        self.sandbox = sandbox
        super().__init__(f"無法直接修改 {path}，工具只會變更沙盒裡的副本。\n{_WAYS_IN}")


class MinecraftSavesPathError(SafetyError):
    """路徑指向 Minecraft 自己的存檔目錄。

    這個檢查**優先於** sandbox 檢查——有人把 `.minecraft` 複製進 sandbox 也一樣擋。
    使用者對原存檔 apply 時實際會走這一條，不是上一條。
    """

    title = "存檔目錄受保護"

    def __init__(self, *, path) -> None:
        self.path = path
        super().__init__(f"工具不會變更 .minecraft\\saves 內的存檔：{path}\n{_WAYS_IN}")


class BackupFailedError(SafetyError):
    """備份不成功。**中止**——絕不允許「備份失敗但繼續寫」。"""

    title = "備份建立失敗"

    def __init__(self, *, path, directory, detail: str) -> None:
        self.path = path
        self.directory = directory
        self.detail = detail
        super().__init__(
            f"無法建立存檔備份（{detail}）。\n"
            f"請確認磁碟空間充足，且檔案未被佔用。未變更任何檔案。"
        )


class BackupRestoreFailedError(SafetyError):
    """回滾時有檔案還原失敗。訊息必須含備份目錄的絕對路徑。

    使用者永遠要有一條救回來的路——即使我們的還原壞了，備份還在那裡。
    """

    title = "自動還原未完成"

    def __init__(self, *, directory, failures) -> None:
        self.directory = directory
        self.failures = failures
        listed = "\n".join(f"  {path}：{detail}" for path, detail in failures)
        super().__init__(
            f"寫入失敗且未能完全還原，備份保存在 {directory}。\n"
            f"請手動將備份檔案複製回地圖資料夾。\n"
            f"沒能還原的檔案（{len(failures)} 個）：\n{listed}"
        )


class SandboxTargetExistsError(SafetyError):
    """`sandbox import` 的目標已經存在。覆蓋要明講（`--replace`）。"""

    title = "地圖已存在"

    def __init__(self, *, target) -> None:
        self.target = target
        super().__init__(
            f"沙盒已有同名地圖 {Path(str(target)).name}（{target}）。\n"
            f"重新匯入會刪除沙盒裡的副本（含已寫回的譯文與資源包），翻譯檔不受影響。"
            f"要覆蓋請加 --replace。"
        )


class SandboxTargetInsideSourceError(SafetyError):
    """匯入目標落在來源底下——複製會把自己一直複製進自己。"""

    title = "沙盒位置不正確"

    def __init__(self, *, source, target) -> None:
        self.source = source
        self.target = target
        super().__init__(
            f"沙盒位置 {target} 在要匯入的地圖 {source} 裡面，會造成無限複製。\n"
            f"請把地圖放在別的資料夾。"
        )


class WorldChangedSinceExtractError(SafetyError):
    """世界的內容跟 `extract.json` 記的不一樣了。

    per-node 的 `expected_encoding` 守門看得到「形狀變了」，看不到「形狀沒變
    但內容變了」（`occurrence.raw_snapshot` 那個更精細的缺口還在等）。這裡擋的
    是更粗但更早的那一層：整份世界的指紋對不上，代表這份 editplan 是基於一個
    已經不存在的快照算出來的，動任何一個位元組之前先問清楚。
    """

    title = "地圖已變更"

    def __init__(self, *, world, expected: str, actual: str) -> None:
        self.world = world
        self.expected = expected
        self.actual = actual
        super().__init__(
            "地圖在抽取文字後被修改過，為避免存檔損壞已中止。\n"
            "請重新抽取文字，過程中可選擇保留已填的譯文（--keep-translations）。"
        )


class FormatError(McmtError):
    """磁碟上的資料不是我們認得的形狀。"""

    title = "檔案格式錯誤"


class UnknownCompressionError(FormatError):
    """chunk 的壓縮類型位元組不是 1/2/3/4。

    絕不猜測、絕不 fallback 到 zlib——猜錯就是寫壞別人的存檔（CLAUDE.md §1.3）。
    訊息必須含實際數值與 chunk index（同一節）。
    """

    title = "不支援的壓縮格式"

    def __init__(self, *, raw_byte: int, type_id: int, chunk_index: int) -> None:
        self.raw_byte = raw_byte
        self.type_id = type_id
        self.chunk_index = chunk_index
        super().__init__(
            f"第 {chunk_index} 個區塊的壓縮格式不支援"
            f"（類型 {type_id}，原始位元組 0x{raw_byte:02x}）。\n"
            f"工具只認得 1=gzip／2=zlib／3=未壓縮／4=lz4，不會亂猜，以免寫壞存檔。"
        )


class CorruptCompressedDataError(FormatError):
    """壓縮類型認得，但資料本身解不開。"""

    title = "區塊資料損毀"

    def __init__(self, *, type_name: str, chunk_index: int, detail: str) -> None:
        self.type_name = type_name
        self.chunk_index = chunk_index
        self.detail = detail
        super().__init__(
            f"第 {chunk_index} 個區塊的 {type_name} 資料解壓失敗（{detail}）。\n"
            f"該區塊不會被翻譯或變更。"
        )


class TruncatedRegionError(FormatError):
    """region 檔比它自己宣告的短：header 或 payload 跑到檔尾之外。"""

    title = "地圖檔案損毀"

    def __init__(self, *, path, detail: str, chunk_index: int | None = None) -> None:
        self.path = path
        self.chunk_index = chunk_index
        self.detail = detail
        where = "" if chunk_index is None else f"第 {chunk_index} 個區塊"
        super().__init__(
            f"{path} 內容不完整{('（' + where + '）') if where else ''}：{detail}。\n"
            f"若為下載的地圖，請重新下載存檔。"
        )


class MalformedRegionError(FormatError):
    """region 的 header 自相矛盾：偏移指進表格、磁區數為 0、長度溢出磁區等。"""

    title = "地圖檔案損毀"

    def __init__(self, *, path, chunk_index: int, detail: str) -> None:
        self.path = path
        self.chunk_index = chunk_index
        self.detail = detail
        super().__init__(
            f"{path} 的檔案結構有誤（第 {chunk_index} 個區塊）：{detail}。\n"
            f"若為下載的地圖，請重新下載存檔。"
        )


class ExternalChunkError(FormatError):
    """chunk 的內容在外部 `.mcc` 檔。v1 拒絕處理。

    帶 `0x80` 旗標時 region 內只有 header，「原封複製壓縮位元組」複製到的是空的。
    這條寫入路徑在語料 16.2 萬 chunk 裡有 0 個樣本、完全沒測過（CLAUDE.md §1.4）。
    """

    title = "不支援的地圖格式"

    def __init__(self, *, chunk_index: int) -> None:
        self.chunk_index = chunk_index
        super().__init__(
            f"此地圖有區塊存放在外部 .mcc 檔（區塊過大時 Minecraft 會另存，"
            f"第 {chunk_index} 個區塊），目前無法安全處理。\n未變更任何檔案。"
        )


class CodecError(FormatError):
    """`decode` 步驟裡那份巢狀文件解不開。

    不是「當作純文字算了」——那份文件解不開就代表我們讀不懂這個節點，讀不懂的
    節點不該被翻譯，更不該被寫回去。
    """

    title = "文字無法解析"

    def __init__(self, *, codec: str, detail: str) -> None:
        self.codec = codec
        self.detail = detail
        super().__init__(f"{codec} 解碼失敗：{detail}")


class DatFormatError(FormatError):
    """`.dat` 檔既不是 gzip、也不是 zlib、也不是裸 NBT，或者解析不出來。"""

    title = "檔案無法辨識"

    def __init__(self, *, path, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(f"無法讀取 {path}（{detail}）。")


class DatWriteVerificationError(FormatError):
    """`.dat` 寫出去的位元組讀不回來——原檔沒有被動過。

    `.dat` 是整份重編的（不像 region 有外科式寫入），所以「編壞了」的後果是整個
    檔案沒了。寫入前先回讀驗證，失敗就中止並保留原檔。
    """

    title = "寫入檢查未通過"

    def __str__(self) -> str:
        return f"{super().__str__()}\n請附上 mcmt-error.log 回報問題。"


class DatapackWriteVerificationError(FormatError):
    """datapack 的 zip 重寫出來讀不回來——原檔沒有被動過。

    和 `DatWriteVerificationError` 是同一條理由，但**爆炸半徑更大**：`.dat` 編壞
    了是一個檔案沒了，zip 編壞了是**整份壓縮檔裡的每一個條目**都沒了——包括我們
    根本沒要改的 `pack.mcmeta`、`function/`、`loot_table/`。所以替換之前要確認
    兩件事：整份 zip 的 CRC 全對（`testzip()`），而且我們剛改過的那個條目仍然是
    讀得回來的 JSON。
    """

    title = "寫入檢查未通過"

    def __str__(self) -> str:
        return f"{super().__str__()}\n請附上 mcmt-error.log 回報問題。"


class ChunkTooLargeError(FormatError):
    """chunk 大到一個 region 槽放不下（超過 255 個磁區）。

    Minecraft 遇到這種情況會把 chunk 外置成 `.mcc`——而那條寫入路徑 v1 不支援，
    在語料 16.2 萬 chunk 裡也有 0 個樣本。寧可拒絕，不寫一條沒測過的路徑。
    """

    title = "區塊超出容量"

    def __init__(self, *, chunk_index: int, sectors: int) -> None:
        self.chunk_index = chunk_index
        self.sectors = sectors
        super().__init__(
            f"寫入後第 {chunk_index} 個區塊的容量（{sectors} 個磁區）超出遊戲上限，無法儲存。\n"
            f"未變更任何檔案。"
        )


class UnsupportedWorldStructureError(FormatError):
    """世界的 chunk 結構不是 1.21 的形狀（多半是 1.12）。v1 拒絕處理整個世界。

    `reason` 是機器可讀的分類，讓 `doctor` 能統計是哪一種症狀：
    `level_wrapper` / `legacy_sign_text` / `missing_data_version`。
    """

    title = "包含舊格式區塊"

    def __init__(self, *, reason: str, chunk_index: int, detail: str) -> None:
        self.reason = reason
        self.chunk_index = chunk_index
        self.detail = detail
        super().__init__(
            f"第 {chunk_index} 個區塊是舊格式（{reason}）：{detail}。\n"
            f"這類區塊（遊戲尚未升級的區域）會略過不處理。"
        )


class RuleError(McmtError):
    """規則引擎出了問題。"""

    title = "處理程序未完成"


class RuleEngineDidNotConvergeError(RuleError):
    """不動點迭代跑到上限還在長新標籤——多半是兩條規則在互相餵。

    **不可靜默停止。** 停下來回傳「現有結果」會產生「有時候少抽幾個節點」這種最難
    查的 bug：同一個世界跑兩次結果不同，而且沒有任何跡象。
    """

    def __init__(self, *, iterations: int, added: dict) -> None:
        self.iterations = iterations
        self.added = added
        listed = "\n".join(
            f"  {name}：{sorted(labels)}" for name, labels in sorted(added.items())
        )
        super().__init__(
            f"規則解析跑了 {iterations} 輪仍未在預期內完成。請附上 mcmt-error.log 回報此問題。\n"
            f"最後一輪新增的標籤：\n{listed}"
        )


class WriteError(McmtError):
    """要寫出去的東西本身有問題。**在動磁碟之前**發現的那一類。"""

    title = "內部處理錯誤"


class PlaceholderResidueError(WriteError):
    """要寫出去的字面文字裡還有 `[[n]]`。**拒絕整份 plan，不是跳過這一筆。**

    殘留代表上游（後端或驗證）算錯了，而算錯的東西不會只錯一筆。寫出去玩家會看到
    那串記號。
    """

    def __init__(self, *, text: str, tokens: list) -> None:
        self.text = text
        self.tokens = tokens
        super().__init__(
            f"寫入內容包含未完成替換的標記（{' '.join(tokens)}），未變更任何檔案。\n"
            f"請回報此問題。文字：{text!r}"
        )


class InvalidChunkWriteError(WriteError):
    """餵給 `write_region` 的 chunk 描述不合法。

    這些都是呼叫端的錯誤（重複 index、index 超出範圍、非法壓縮類型、空 payload），
    寫出去才發現就太晚了——那時磁碟上已經有一份我們自己讀不回來的 region。
    """

    def __init__(self, *, detail: str) -> None:
        self.detail = detail
        super().__init__(f"不合法的 chunk 寫入描述：{detail}\n請回報此問題。")


class WorldNotFoundError(McmtError):
    """給定的路徑不存在。"""

    title = "找不到資料夾"

    def __init__(self, path) -> None:
        self.path = path
        name = Path(str(path)).name or str(path)
        super().__init__(f"{name} 不存在，或已被移動、改名。\n完整路徑：{path}")


class NotAWorldError(WorldNotFoundError):
    """路徑存在，但不是 Minecraft 地圖（沒有 `level.dat` 也沒有 `region`）。"""

    title = "不是有效的地圖"

    def __init__(self, path) -> None:
        self.path = path
        text = (
            f"{path} 沒有 Minecraft 存檔檔案（找不到 level.dat 與 region）。"
        )
        if ".mcmt-out" in Path(str(path)).parts:
            text += (
                f"\n這是 mcmt 的輸出資料夾，地圖本身在 sandbox\\{Path(str(path)).name}。"
            )
        McmtError.__init__(self, text)


class InputFileNotFoundError(McmtError, FileNotFoundError):
    """使用者指定的輸入檔不存在。

    同時是 `FileNotFoundError`：既有呼叫端與測試照舊抓得到。
    """

    title = "找不到翻譯檔"

    def __init__(self, path, *, kind: str = "翻譯檔") -> None:
        self.path = path
        self.title = f"找不到{kind}"
        McmtError.__init__(
            self,
            f"{Path(str(path)).name} 不在指定的位置，請確認檔名與資料夾。\n完整路徑：{path}",
        )


class InvalidJsonFileError(McmtError, ValueError):
    """待翻檔（或 extract.json）不是合法的 JSON。

    把 `json.JSONDecodeError` 的「Expecting property name…line 1 column 2 (char 1)」
    換成使用者看得懂的「第幾行、出錯那一行與前後各一行」。
    """

    title = "翻譯檔無法讀取"

    def __init__(
        self, *, path, line: int, column: int, context: list[tuple[int, str]], kind: str = "翻譯檔"
    ) -> None:
        self.title = f"{kind}無法讀取"
        self.path = path
        self.line = line
        self.column = column
        self.context = context
        shown = "\n".join(f"  {number:>4} | {text}" for number, text in context)
        super().__init__(
            f"{Path(str(path)).name} 第 {line} 行第 {column} 字附近有語法錯誤。\n{shown}\n"
            f"未變更任何檔案。"
        )


class TranslationsMismatchError(McmtError, ValueError):
    """翻譯檔不是為這份 extract 產生的。

    指紋是技術細節，不放在畫面上；留在屬性裡給日誌。
    """

    title = "翻譯檔與地圖不符"

    def __init__(self, *, found: str, wanted: str) -> None:
        self.found = found
        self.wanted = wanted
        super().__init__(
            "這份翻譯檔不是由目前的掃描紀錄產生，已中止寫入。\n請使用最新產生的翻譯檔。"
        )


class TranslationsExistError(McmtError, FileExistsError):
    """抽取的目標已經有待翻檔。覆蓋要明講。"""

    title = "檔案已存在"

    def __init__(self, path) -> None:
        self.path = path
        McmtError.__init__(
            self,
            f"已有 {Path(str(path)).name}，重新抽取會覆蓋它（舊檔會先另存為 .bak-時間）。\n"
            f"要覆蓋請加 --replace；想保留舊檔就用 --out 指定另一個資料夾。",
        )


class PackMetaError(McmtError, ValueError):
    """地圖自己的 `pack.mcmeta` 讀不懂。不猜——猜錯會讓整包被拒。"""

    title = "資源包設定錯誤"

    def __init__(self, *, path, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(
            f"地圖的 pack.mcmeta 格式有誤（{path}）：{detail}\n"
            f"請修正該設定檔格式，或暫時移走後再試。"
        )


class NamespaceConflictError(McmtError, ValueError):
    """`--namespace minecraft`：覆寫原版 key 會改掉原版所有語言的文字。"""

    title = "命名空間衝突"

    def __init__(self, namespace: str = "minecraft") -> None:
        self.namespace = namespace
        super().__init__(
            "命名空間不能設為 minecraft（會覆蓋遊戲內建文字）。\n請改用其他名稱（預設為 mcmt）。"
        )


class FileAccessDeniedError(McmtError, PermissionError):
    """檔案被佔用，或沒有寫入權限。"""

    title = "檔案存取被拒"

    def __init__(self, path) -> None:
        self.path = path
        super().__init__(
            f"無法寫入 {path}，檔案可能被其他程式佔用，或沒有寫入權限。\n"
            f"請關閉 Minecraft 後再重試。"
        )


class MissingDependencyError(McmtError):
    """需要一個可選相依，但它沒被安裝。訊息必須告訴使用者裝什麼。"""

    title = "缺少必要套件"


class ExternalChunksFoundError(FormatError):
    """整張地圖層級的外部 `.mcc` 閘門：`doctor` 數到了外部 chunk，**硬中止**。

    跟 `ExternalChunkError`（讀到某一個 chunk 時拋）是同一個理由、不同的時機：
    這個在匯入之前就擋，所以真的是「未變更任何檔案」。這條寫入路徑沒有任何樣本
    走過（CLAUDE.md §1.4），沒有任何旗標可以繞過。
    """

    title = "不支援的地圖格式"

    def __init__(self, count: int) -> None:
        self.count = count
        super().__init__(
            f"此地圖有 {count} 個區塊存放在外部 .mcc 檔（區塊過大時 Minecraft 會另存），"
            f"目前無法安全處理。\n未變更任何檔案。"
        )


class OriginMissingError(McmtError):
    """要重新開始，但沙盒副本的來源（原存檔）已經不在了。

    在刪掉沙盒裡任何東西之前就要發現：沒有原存檔就沒辦法重新匯入，刪了就回不去。
    """

    title = "找不到原存檔"

    def __init__(self, *, name: str, source) -> None:
        self.name = name
        self.source = source
        where = str(source) if source else "（沙盒裡沒有記錄來源）"
        super().__init__(
            f"沙盒裡的 {name} 是從 {where} 匯入的，但那個位置已經不存在。\n"
            f"請把原存檔放回去，或直接把地圖拖曳至程式。未變更任何檔案。"
        )


class NotATranslationsFileError(McmtError):
    """拖進來的 `.json` 不是 mcmt 產生的翻譯檔。"""

    title = "不是翻譯檔"

    def __init__(self, path) -> None:
        self.path = path
        super().__init__(
            f"{Path(str(path)).name} 不是 mcmt 產生的翻譯檔。\n"
            f"請拖入地圖資料夾，或抽取時產生的 translations.語言.json。"
        )


class TranslationsMapNotFoundError(McmtError):
    """翻譯檔對不上沙盒裡任何一張地圖（地圖被刪了，或從沒抽取過）。"""

    title = "找不到對應的地圖"

    def __init__(self, path) -> None:
        self.path = path
        super().__init__(
            f"沙盒裡沒有 {Path(str(path)).name} 對應的地圖。\n"
            f"請先把地圖拖曳至程式抽取文字。未變更任何檔案。"
        )
