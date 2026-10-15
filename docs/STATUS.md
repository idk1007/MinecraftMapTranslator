# 專案進度 — mcmt

**這份檔案是跨對話的交接點。** 新開一個 Claude Code 對話時先讀這裡，就知道做到哪、下一步是什麼、哪些結論不能重新推導。
**每完成一個里程碑就更新這裡**，和「進遊戲驗證要寫回 `SPIKE_RESULT.md`」是同一個紀律：單人開發沒有第二個人會提醒你。

最後更新：**2026-10-15（晚）**（**「做成給一般人用的 exe」第 1–2 步完成。**
目標：打開 exe → 把地圖拖進視窗 → 一步步對話框，沒有黑色 cmd 視窗。已定案的決定
（不必重推）：沙盒放 exe 旁邊；使用者面對的詞是「沙盒」；`.mcc` **硬中止**、舊格式
區塊與損毀檔案**問一聲**（繼續／取消）；覆蓋重來時**問**是否保留舊譯文，保留的話
依 `unit_id` 搬、對不上的列清單，**不做模糊比對**；打包 Windows 資料夾版 zip、
關 UPX、附 `mcmt.exe`（無黑視窗）與 `mcmt-cli.exe`、GitHub 附雜湊；README 由
使用者自己構思，不替他改。措辭的來源與逐條對照在 `docs/error-messages-review.md`。

- **第 1 步（訊息）** `145b7ab` `36588aa` `0a94c4c`：每個例外是「【標題】＋內容」
  （`McmtError.title`）；argparse 英文錯誤中文化；沒預期的例外寫
  `sandbox\mcmt-error.log` 不印堆疊（日誌放沙盒內，安全規則 1）；apply 摘要列出
  被拒條目的位置與原文；覆蓋待翻檔前自動另存 `.bak-時間`；apply 先擋不能寫的地方。
  `write/` 與 `safety/` **沒動**：D3 的驗證失敗訊息只在例外類別補標題與一句
  「請附上 mcmt-error.log」。
- **第 2 步（流程邏輯，不含視窗）** `d2c6628` `91ede5d`：`extract --keep-translations`
  （`extract/carry.py`）；`mcmt/flow.py` 的狀態機，只看沙盒裡有什麼判斷四個狀態
  （還沒抽取／譯文全空／有譯文未寫回／已寫回過）；介面 `Ui` 只有 `log`／`ask`／
  `choose_language`／`open_path` 四個方法，測試用假介面，終端機版是 `mcmt drop`。
  **會刪東西的「重新開始」在動手前先檢查原存檔還在不在、現在還能不能處理。**
  資料夾同名但來源不同的兩張地圖不會被當成同一張。真實地圖（`Be-boxed`，22 個
  單位）整條流程走過：抽取 5.9 秒、寫回 2 秒、重新開始 6.2 秒、沿用 20 筆譯文、
  重新匯入後 `resources.zip` 與原存檔位元組一致。988 passed／contracts 48 passed。
- **第 3 步（視窗）** `3280d58` `783365f`：沙盒在打包後固定放 exe 旁邊
  （`safety/paths.py`，獨立 commit，`sys.frozen` 時才生效）；`mcmt/gui/`（tkinter，
  拖放用 `ctypes` 接 `WM_DROPFILES`，不加第三方套件，另有「選擇資料夾…」後備），
  入口 `mcmt-gui`。**[實測] 在 Windows 視窗程序的回呼裡碰 tkinter 會讓 Python
  崩潰**，回呼只能把路徑丟進佇列。測試會真的送一個 `WM_DROPFILES`、真的建視窗並
  自動按按鈕走完抽取與寫回；驗不到外觀與實際拖放手感，**等使用者實際操作回報**。
  1003 passed。
- **下一步**：使用者試用視窗版後回報外觀／手感；第 4 步打包（PyInstaller 資料夾版、
  關 UPX、`mcmt.exe`＋`mcmt-cli.exe`、附 lz4、SHA256 雜湊檔；上傳 Releases 由使用者做）。

前一次更新：**2026-10-15**（**指令方塊的前導斜線**，commit `b70518b`。[實測]
`escape_the_illusion` 的指令方塊寫 `/tellraw`、`/title`，掃描器把 `/tellraw`
當成不認得的動詞整條略過。`scan_command_string` 新增 `allow_leading_slash`，只有
指令方塊與指令方塊礦車開啟；`.mcfunction` 不放寬（函式檔裡前導 `/` 是語法錯誤）。
這張地圖略過數 931 → 787。902 passed。

**已知殘餘**：`_has_nested_command_reference`（L3 檢查）認 click_event 裡的指令時
也不認前導斜線，而 click_event 的 `run_command` 慣例上帶 `/`。後果是那種 component
不會被保守地整個跳過，外層文字照翻、裡面那條指令的文字沒翻——是少翻，不是寫壞。）

前一次更新：**2026-10-14**（**指令文字已知缺口 A／B／C 殘餘／E 全部處理完畢。**

- **缺口 E（`write/command_span.py`）已修**，commit `5dfb416`：SNBT 字串常值與
  原生 SNBT component 的輸出裡，C0 控制字元與 DEL 一律寫成跳脫序列
  （`\n` `\r` `\t` `\b` `\f`，其餘 `\uXXXX`）；`say`／`me`（沒有跳脫語法）含控制
  字元的譯文改為拒寫（`unsupported_encoding`，detail 寫明控制字元）。amulet 不認
  `\n` 跳脫，`assert_command_reparses` 單獨抓不到這一格，新測試直接斷言輸出無控制
  字元並用獨立的解碼器比對原文。`[文件]` 1.21.5 起 SNBT 支援這些跳脫；1.21.11 的
  實際解析仍 `[待驗]`。
- **缺口 A（`scan/command.py`）已修**，commit `0b686f0`：`_find_component` 接受
  `custom_name` 與 `minecraft:custom_name`，別的命名空間照舊不碰。端到端原本釘住
  缺口的測試方向反過來，dispatch 組合 6 → **7** 格（`("region_chunk","snbt","translate")`）。
- **缺口 B：改成掃描端跳過**（使用者裁定），commit `e9b03d2`。原計畫是讓寫入層
  讀得回 `command → snbt → json_component` 三步鏈；但 [遊戲實測 M0-3] 當初就是
  用 `/data merge block` 寫入 `messages:['{"translate":…}', …]`——**正是缺口 B 的
  形狀**——遊戲顯示字面文字。修寫入層只會把一個亂碼換成另一個亂碼。現在
  `scan/command.py::_yield_message` 用嗅探器判形狀，四種舊式 JSON 跳過並計入
  `skipped_legacy_json_in_native_chunk`（沿用既有計數器，不動合約）；`'""'` 從
  `skipped_empty` 改計入這裡（[遊戲實測 M0-4]）。寫入層讀不回三步鏈這件事保留
  成兜底。CLAUDE.md 二節的 command text 段落已同步。
- **缺口 C 殘餘：已補**，commit `4be093e`（`write/` 獨立 commit）。
  `_apply_decode_group` 的三道守門抽成 `write/common.py::guard_command_edits`，
  `.mcfunction` 的資料夾式與 zip 式都改呼叫它（長度 → 重新解碼 leaf → 形狀與
  `raw_snapshot`），`_guard_by_length` 刪除。使用者把字改成一樣長的另一句時現在
  會拒寫。
- `docs/m-command-checklist.md` 第四節改寫：4a 的預期改成「形式 A／B 都顯示字面
  文字」，要看的是有沒有紅字與多出來的反斜線；4c 從「缺口修好後的完整管線覆核」
  改成「確認跳過的前提成立、工具沒碰它」；新增 4e（控制字元跳脫）。

- **指令文字進遊戲驗證完成，全部 PASS**（`docs/m-command-checklist.md`，結果見
  `SPIKE_RESULT.md`「指令文字 M-command 遊戲實測」）：①②③⑤、`.mcfunction`、
  4a（雙引號跳脫）、4d（裸字串 in_place）、4e（`
` 跳脫）升成 `[遊戲實測]`；④ 證實
  字串包裝 JSON 在 1.21.11 是字面文字，缺口 B 的裁定有了直接證據。checklist 本身
  兩處錯誤（③ 的前綴範例、4d 同文兩筆）已修正。

- **CLI 摘要的拒寫說明**：每個 reason 底下印出 detail（`143c688`），不動合約。
  遊戲版本確認為 1.21.11。

898 passed／contracts 48 passed。

前一次更新：**2026-09-13**（**`Against Iskerside [1.21.11]` 翻譯失敗事後檢查，兩個修正。**
使用者實際拿一張地圖跑壞了，回頭查出兩個獨立缺陷：

**(1) 指令文字漏了 M13b 的「已在地化就跳過」守門**（`scan/command.py`）。
`data merge entity … {text:{color:black,translate:"text.iskerside.news1.text"}}`
這類指令——`text` 是 text_display 的**欄位名**，值是一棵指向地圖自己在地化系統
（它自帶 en_us/ru_ru 語言檔＋`text.iskerside.*` key）的 component。`_yield_tag`
（四個 yield 路徑的收斂點）原本只擋 L3 巢狀指令引用，沒擋 translate 節點；
build.py 的同名守門走的是**攤平後的骨架**，看不到被 `text` 這層外殼藏起來的
`translate`——攤平時巢狀 compound 被直接 `str()` 掉。後果：23 個
`command_component_text` 單位被抽成 Python dict 的字串化，apply 後把地圖原本
的多語言支援靜默蓋掉。修法：`_yield_tag` 加一個遞迴版 `_contains_translate`，
任何一處有 `translate` 節點就跳過、計入 `skipped_already_localised`（重用既有
計數器，不動合約）。commit `a06b3bb`。

**(2) 不支援的世界結構被 `extract`／`apply` 靜默吞掉，`doctor` 卻整個拒絕**。
這張地圖同時暴露了另一件事：它是 1.20 世代地圖被 1.21.11 開過，`DataVersion`
橫跨 3218～4671，1,519 個 chunk 還帶 1.12 的 `Level` 包裝層。`doctor` 正確地
拒絕整個世界，但 `scan/sources/region.py`／`entities.py` 對這種
`UnsupportedWorldStructureError` 原本跟磁區偏移錯誤、未知壓縮類型這些**真正
損毀**的 chunk 共用同一個 `skipped_chunk` 計數器，而且這個計數器根本沒被接進
`extract.json`——使用者上次那次「apply 成功」的報告完全沒有任何跡象顯示有
1,519 個 chunk 從未被掃到。

> **討論後決定：不讓 `extract`／`apply` 也跑 doctor 那道拒絕整個世界的閘門**
> ——使用者明確要「警告後仍可繼續」，不要強制中止（之後會做一個更精簡的使用者
> 輸入包裝層，那個閘門要不要做成硬性中止是那時候的設計決定，不是現在）。
> 所以這裡做的是**讓警告可見**，不是**擋下**：
> `UnsupportedWorldStructureError` 現在有自己的計數器 `skipped_unsupported_structure`
> （與 `skipped_chunk` 分開），接進 `extract.json` 的 `stats` 與 `mcmt extract`
> 的 CLI 摘要（「不支援的世界結構（1.12 舊格式，這幾個 chunk 完全沒被掃到）」）。
> 這個決定是**有條件的**：如果將來的包裝層設計改成「doctor 拒絕就整個流程中止
> 不給使用者選」，或者允許裸指令繞過包裝層直接跑 `extract`，這個「跳過但可見」
> 的設計就不夠了，要重新考慮在函式庫層強制拒絕。

886 passed（+4）／contracts 48 passed。

前一次更新：**2026-09-06**（**「command text」整支分支 review 後的修正波。**
review 判定「修完可以合併」，兩個不在既有四個已知缺口裡的缺陷已修：**(C1)**
`.mcfunction` 在 1.20 及以前的**複數 `functions/`** 目錄下完全隱形且沒有任何
計數器（[實測] `Arena of Darkness` 120 個檔案全在複數目錄，摘要跟「這張地圖
沒有 function」一模一樣）；**(C2)** `data merge` 的**裸字串**告示牌訊息被寫成
異質 SNBT list，指令方塊寫得進磁碟卻再也跑不動，而報告說 `unwritten: []`
——span 完全正確、錯的是型別，`write/native.py::apply_to_list` 守著的 list
同型不變式被這條新路徑整個繞過。另外 **(I2)** `.mcfunction` 補上長度守門
（那個缺口原本被記成「無害的 no-op」，**那是錯的**，見下方缺口 C），
**(I4)** `format_result()` 從零覆蓋補上測試。新增安全網
`assert_command_reparses()`：每一次指令 splice 之後都問一句「這還解得回來嗎」，
套用在每一格 dispatch 組合與端到端全世界掃描上——C2 證明「span 抓對範圍」這
一條線單獨不夠。端到端 dispatch 組合 5 → **6** 格。**不動合約、不 bump
SCHEMA_VERSION**（C2 重用既有的 `command_say_text` category）。
缺口 A（`give` 命名空間組件鍵）與 B（字串包裝 JSON 的 `data merge` 寫入路徑）
**維持已知限制**，pinned 測試原樣保留。878 passed／contracts 48 passed。）

前一次更新：**2026-09-05**（**「command text」功能落地並對 MP2 全掃驗證。**
指令方塊的 `Command` 與 datapack 的 `.mcfunction` 現在會解析白名單動詞
（`say`／`me`／`tellraw`／`title`／`bossbar`／`scoreboard objectives add`／
`data merge`／`give`／`item`），把裡面的可翻文字抽出來、apply 時外科式寫回
（動詞前綴原封不動，只換引數）。13 個任務，SCHEMA_VERSION **6 → 7**（editplan
的 decode 步驟鏈與指令文字守門）。設計文件
`docs/superpowers/specs/2026-09-05-command-text-design.md`。**MP2 全掃**
（doctor → extract → no-op 譯文 → 真實 apply → 還原 → doctor 覆核 byte 一致、
`world_fingerprint` 不變）：新增 `command_say_text` 150 單位 ／
`command_component_text` 68 單位，3,331 筆 edit 全部寫入、**0 筆拒寫**，其中
251 筆落在 `data.zip` 內的 `.mcfunction`、8 筆在指令方塊。L3（巢狀指令參照）
在 MP2 是 **0**，行尾延續 2,094 條（佔非註解指令行 1.8%）——方案 2 零收益，
不做。細節與四個已知缺口見 `SPIKE_RESULT.md`「指令文字方案 1 MP2 全掃」。
已知缺口清單新增 command text 缺口 A–D〔見下方〕：Task 11 釘住的三個（`_find_component`
不認命名空間組件鍵、`_decode_command_leaf` 不能還原字串包裝 JSON 訊息、
`mcfunction_apply` 無重放守門）＋ 本輪新發現一個（三個 `skipped_command_*`
stats 有 schema 沒接進 `emit.py`）。〔2026-09-06 後記：D 已修；C 補上長度守門
但 `raw_snapshot` 那層仍缺；A、B 維持已知限制。〕**進遊戲驗證仍 `[待驗]`**：指令文字四項
（tellraw／data merge／say 的算繪＋`_snbt_string_literal` 的雙引號跳脫被
1.21.11 指令解析器接不接受）的可重跑程序已寫成 `docs/m-command-checklist.md`，
等有人開 Minecraft 跑一次、把結果寫回 `SPIKE_RESULT.md`。）

前一次更新：**2026-09-03**（材質包過期 bug 修掉。`all-the-same` 在 Minecraft
**26.2**（pack_format 88）上，`mcmt` 產的 `resources.zip` 宣告 `{75,75}` 被判過期，
連譯文一起沒生效——`pack.py` 的 `PACK_FORMAT = 75` 寫死了。改法：`supported_formats`
上下限都開很寬（`MIN_PACK_FORMAT = 4`「JSON lang 檔第一次存在的版本」到
`FORWARD_PACK_FORMAT = 9999`「實質無上限」）。合併地圖自帶的舊 pack 時只推上限、
下限維持地圖宣告值。取捨：未來 Mojang 真的改 lang 載入邏輯時這個包會**默默失效**
（遊戲載入、譯文不顯示），不是乾淨的錯誤——單人工具不追每個版本，刻意接受。
`CLAUDE.md` §二資源包那條改寫並保留 M0-5 原文加推翻說明。773 passed。這是
`docs/STATUS.md` 已知缺口以外、第一次有真實使用者在比 1.21.11 新的版本上跑這個工具。

前一次更新：**2026-09-01**（M14 第 1 項完成：`README.md` 整篇重寫。舊版還寫著
「尚未有可用的 `src/`」、完全沒提四個指令；新版是給第一次用這個工具的人看的——
核心工作流圖、三條安全規則各一句、安裝、四個指令對照表、一段可以照抄的最短可行
路徑（import → doctor → extract → 編輯 → dry-run → apply → 手動複製回去）、
待翻檔的欄位說明與 `[[n]]` 規則。順手把「第三方」那節過時的 `anthropic`／
`mcmt[llm]` 行刪掉（M9 移出 v1 時就拿掉了）。M14 第 2／3 項（CLI `--help`、
人類可讀報告）對照著 README 重讀過，措辭一致，**沒動**。M14 只剩第 4 項那批
功能缺口（6/7/8/9），那些不是文件的事。

前一次更新：**2026-09-01**（`sandbox/MP2` 用 M13a/M13b 之後的完整掃描重跑一遍
已知缺口第 15 項：doctor 健檢 → extract 全掃 → no-op 譯文 → 真實 `apply` 寫入 →
從備份還原 → doctor 覆核數字與寫入前一致。3,072 筆 edit 全部寫入、0 筆拒寫，
`skipped_already_localised` 第一次在 3,515 筆真實資料上生效，第 5／3 項的批次守門
與 `raw_snapshot` 守門在語料裡形狀最雜的地圖上都沒有暴露新問題，細節見
`SPIKE_RESULT.md`「M13a/M13b 之後 MP2 全掃」。已知缺口清單清空到只剩五項功能性
缺口（6/7/8/9/14），**下一步 M14 已經盤點成可動手的清單**（見下方「M14
CLI／報告／文件」一節）：`README.md` 嚴重過時是唯一確定要做的事，CLI `--help`
與人類可讀報告盤點過都已經夠完整，不用大改。

2026-08-31：M13b 之後陸續清掉九項已知缺口，同一天分批完成：
resourcepack 後端的 in_place/translate_key 分派改由 `strategy_for(category)`
決定；物品白名單補上 `minecraft:block_entity_data`；`region_files`/
`entities_files` 排序鍵正規化成 `/`；`write/in_place.py` docstring 更新；
`write/common.py` 新增 `apply_edits()` 批次入口修掉 native list 多筆 edit
自撞（100 Ways To Die 實測 325 筆 node_changed → 0）；`world_fingerprint`／
`doctor` 補上 `level.dat`／`scoreboard.dat`／datapack 涵蓋範圍；`run_apply`
比對世界指紋（新增 `WorldChangedSinceExtractError`）；`occurrence.raw_snapshot`
從 extract 到 editplan 到 write/ 守門全線接通，SCHEMA_VERSION 5 → 6。
下一步仍是 M14，或繼續清剩下的已知缺口）

---

## 一句話現況

**M0–M8、M10–M13b 完成，而且沒有任何一項卡在「要進遊戲」了。** 整條鏈
（`import → extract → 人工翻譯 → apply`）有自動化測試釘住，三條寫入路徑
（translate key、in_place、legacy JSON）都走得通，字寬預算是量出來的、`enforcement`
已經是 `error` 而且真的會擋。**M13a 把掃描廣度擴到容器物品與 `entities/*.mca`，
M13b 再擴到 `level.dat`／`scoreboard.dat`／datapack advancement 三個非 region 來源，
「command text」（2026-09-05）再擴到指令方塊 `Command` 與 datapack `.mcfunction`
的白名單動詞文字，SCHEMA_VERSION 6 → 7，MP2 全掃 0 筆拒寫**
——**M14**（CLI／報告／文件）的主體（重寫 `README.md`）已於 2026-09-01 完成，
CLI `--help` 與人類可讀報告盤點過不需大改；剩下的是幾項功能缺口（見「已知缺口」）。

~~M1 只差「節點形狀分佈」~~ → **M5.6 已補上**，`doctor` 現在會報形狀分佈與「有多少節點會被跳過不翻」。

## 現在這個工具能做什麼

四個指令，全部在真實地圖上跑過：

```
mcmt doctor <世界>                     健檢（唯讀）：DataVersion 分佈、節點形狀分佈、
                                       有多少節點會被跳過不翻、可不可以處理
mcmt sandbox import <來源世界>          唯一合法的把世界帶進 sandbox 的入口
mcmt extract <sandbox 世界>            → translations.<lang>.json（**人編輯這個**）
mcmt apply <sandbox 世界> --translations …   → resources.zip + 外科式寫回
                                       （--dry-run 完全不碰存檔，只產 editplan.json）
```

實跑數字（M13a 接上物品與實體之後）：`Arena of Darkness`（88,969 chunk）extract 出
**902 個翻譯單位**、`100 Ways To Die`（6,465 chunk）**1,348 個**——細節見下方 M13a 節。
apply 在探測世界上改動 1 個 chunk、**原封複製 929 個**。

`sandbox/` 現有三份副本可用：`100 Ways To Die`(95M)、`Arena of Darkness`(378M)、
`roundtrip`(18M，**已翻好且驗證過的探測世界**)。不需要就整個資料夾刪掉。

---

## 架構調整（2026-08-21）：取消內建 LLM 翻譯

**核心工作流是純檔案解耦**，工具不做機器翻譯、不呼叫任何 API、執行期沒有網路相依：

```
mcmt extract → translations.<lang>.json（人直接編輯）→ mcmt apply
```

三處落地，都已完成：

1. **合約 `SCHEMA_VERSION` 3 → 4**。`translations` 的 entry 從 `{text, status}` 變成 `{source, target, note, where}`——舊形狀只有 unit_id 當鍵，人打開檔案看不到自己在翻什麼。`apply` **只讀 `target`**；`source` 不拿去比對（翻譯途中改短它是常見的事），綁定靠 `extract_fingerprint`。空 `target` = 未翻譯，`status: skip` = 刻意不翻，報告分得開。
2. **單一段落不再插 `[[0]]`**。純文字就是純文字；每行都掛無意義前綴，譯者容易順手刪掉，而刪掉之後佔位符驗證會硬失敗、錯卻是我們造成的。
3. **M9 移出 v1**，`pyproject` 拿掉 `[llm]` extra。原本屬於 M9 的兩件事沒有消失：佔位符驗證 → M11 守門 + `mcmt check`；寬度量測 → M8 的表。

**M8 的定位因此變重要**：寬度預算要**寫進待翻檔的 `note` 給人看**，譯者得先知道「這行只放得下十個字」才有辦法斟酌用詞。事後才報超寬對人沒有幫助。

**沒有放寬的一條**：`[[n]]` 驗證仍是 hard fail。人會犯的錯和機器一樣多，§ 碼染到行尾的後果一樣。

### 一併決定：**不做術語表、不做「不翻」標記、連警告都不做**（2026-08-21）

問題是「一句話裡有要翻和不要翻的部分」，例如 `how are you josh` 該翻成「你好嗎 josh」
而不是「你好嗎 喬許」。

**決定：工具不介入。** 待翻檔把 `source` 放在 `target` 隔壁，譯者看得到原文，人名要
不要留是他的判斷。不做 `glossary.json`、不做 `{{ }}` 之類的保護標記、`mcmt check`
也不為此發警告。

考慮過但沒採用的理由不是「做不到」，是**這是單人翻一張地圖的工具**：譯者就是使用者
本人，他看得懂自己在翻什麼；為了一致性引入一份要維護的清單，成本比它省下的多。

> **未來要重新考慮的唯一觸發點**：M13 補上 lang 檔／datapack 掃描時。
> [實測] MP2 自己的 50,959 個 lang 值裡有 **18,796 個（37%）含 `%1$s`**、847 個含 `§` 碼。
> 那類是**格式參數**不是人名——漏掉一個 `%1$s`，遊戲少填一個玩家名進去。它與人名
> 不同類：機器驗得出來，而且錯了不只是難看。
> v1 目前掃的來源（告示牌、CustomName）裡格式參數實測是 **0**，所以現在不處理是正確的；
> **M13 開工時要重新問一次**，別直接沿用這個決定。

---

## 該讀哪幾份（依序）

| 檔案 | 是什麼 | 什麼時候讀 |
|---|---|---|
| `CLAUDE.md` | **規範**。安全規則、格式規則、key 生成、禁令 | 每次動手前 |
| `docs/STATUS.md` | 本檔。進度與交接 | 每次開新對話 |
| `SPIKE_RESULT.md` | **事實依據**。所有實測結論與證據等級（四級制） | 要引用「為什麼這樣設計」時 |
| `docs/superpowers/plans/2026-08-15-mcmt-architecture.md` | 架構計畫 rev.2。目錄結構、四份合約、A/B/C 題、M0–M14 | 排下一步工作時 |
| `docs/contracts/*.json` | 四份 JSON Schema（`SCHEMA_VERSION = 7`） | 寫任何跨層資料時 |
| `docs/ownership.md` | 模組邊界與三個整合檢查點 | 決定某段程式該放哪裡時 |
| `docs/adr/0007-prior-art-and-licensing.md` | 為何不得對照 maptranslator 原始碼 | 想參考既有實作時 |
| `docs/m0-checklist.md` | M0 可重跑程序（換版本時用） | 要重驗遊戲行為時 |
| `docs/m8-checklist.md` | 字寬校準的可重跑程序（M13 掃到書本後要再跑一次） | 要重驗字寬時 |

---

## 已完成

### 規劃階段（2026-08-15 ～ 08-16）

- 三輪 spike 實測，語料 5 張地圖 / 162,226 chunk，結論全部寫進 `SPIKE_RESULT.md` 並標證據等級
- 四份合約定稿 + `tests/fixtures/contracts/*.sample.json` + `tools/validate_contracts.py`
- `CLAUDE.md`、`docs/ownership.md`、ADR-0007、架構計畫 rev.2

### M0 — 端到端最小驗證（2026-08-17，`[遊戲實測]`）✅

**資源包路線成立**：自訂命名空間 key 由世界根目錄的 `resources.zip` 解出並顯示中文。這是「整個架構的最終證明」，M1 之後的工作不再有被整體推翻的風險。

另得四項結論，其中 M0-3 推翻了一項隱含假設 —— 詳見 `SPIKE_RESULT.md`「M0 遊戲實測」。**最重要的一條**：

> DataVersion **不**決定節點是什麼形狀，但 DataVersion **決定遊戲會不會替該節點跑 DataFixer**。
> 因此 DV ≥ 4325 的 chunk 裡的舊式 JSON 字串是**字面亂碼，不是內容** → v1 跳過不翻譯，也不「順手修好」。

合約隨之 bump 到 `SCHEMA_VERSION = 3`：新增 `occurrence.excluded`、`stats.skipped_legacy_json_in_native_chunk`、unit flag `legacy_json_in_native_chunk`，並在 editplan schema 結構性禁止「DV ≥ 4325 + `json_*` encoding」的組合。驗證器 44 passed。

### M1.1 — 壓縮分派（2026-08-17）✅

`src/mcmt/nbtio/compression.py` + `src/mcmt/errors.py` + 22 個單元測試。同時建立 `pyproject.toml` 與 `.venv`（editable 安裝）。

三個實作決定與規範的關係，之後不必重推：

- **`chunk_index` 是必填關鍵字參數**。CLAUDE.md 只要求訊息含 chunk index，但可選參數等於允許呼叫端丟掉它。
- **`decompress_chunk` 收到未遮罩的位元組（如 `0x82`）會拋錯，不順手遮罩**。遮罩是 `parse_compression_byte` 的職責，兩處都做等於允許跳過 parse。
- **type 4 走 lz4-java 的 `LZ4BlockOutputStream` 框架**（`"LZ4Block"` magic + 每區塊 21 bytes 標頭），不是標準 LZ4 frame。無真實樣本，標 `[待驗]`，已寫回 `SPIKE_RESULT.md`。xxhash32 檢查碼不驗（為它引入相依不划算，壞資料會被 NBT 解析擋下）。

已用突變測試確認「先判型別再遮罩」會讓 4 個測試變紅——這條不變式是真的被測到的，不是寫在註解裡而已。

### M1.2 — region 讀取（2026-08-17）✅

`src/mcmt/nbtio/region.py`（`read_region` 產生器 + `RawChunk`）+ 16 個單元測試。

- **payload 是磁碟上的原始壓縮位元組，這層不解壓。** 讀取層若順手解壓，外科式寫入的保證就只剩呼叫端的自律。
- 畸形檔分兩類，因為對 `doctor` 意義不同：`TruncatedRegionError`（檔案比宣告的短）vs `MalformedRegionError`（header 自相矛盾：偏移指進前兩磁區、磁區數 0、長度溢出磁區、非外部 chunk 卻空 payload）。
- `0x80` 只報 `is_external`，**不夾帶政策**——拒絕處理外部 chunk 是 M1.3 的事。
- ~~路徑還沒過 `ensure_readable`~~ → **M2.5 已接上**：`read_region` 現在只收 `ReadOnlyPath`。
- 真實資料健檢（唯讀）：MP2 的 3 個 region、2,952 chunk，全 type 2、外部 0、解壓後都是 TAG_Compound、DataVersion 4556 — 與 `SPIKE_RESULT.md` 一致。

### M1.3 — 世界結構偵測（2026-08-17）✅

`src/mcmt/nbtio/structure.py`（`load_chunk_root` + `ensure_supported_structure`）+ 9 個測試。

- `UnsupportedWorldStructureError` 帶**機器可讀的 `reason`**（`level_wrapper` / `legacy_sign_text` / `missing_data_version`），所以 `doctor` 能 catch 起來統計症狀分佈，不必為了「能報數字」就把閘門做成不拋錯的版本。
- `ensure_supported_structure` 回傳 chunk 自己的 DataVersion，但那只是順路讀到——**形狀一律逐節點嗅探**。
- 放在 `nbtio/` 而不是計畫的 `scan/`：這裡只判斷位元組是什麼形狀、不碰語意，錯誤也都是 `FormatError` 家族；`scan/` 要到 M5 才存在。

**真實資料推翻了一個說法，已寫回 `SPIKE_RESULT.md`：** 「同一世界兩套結構」**不是 1.12 專屬**，而 `Text1..Text4` 是「1.20 之前的告示牌格式」**不是「1.12 結構」**。證據：`Find The Button No Cakewalk`（1.18.2）有 852 個帶 `Level` 包裝的 chunk（抽驗 DataVersion 1963）與 15 個 DataVersion 2975、容器是現代 `block_entities` 但告示牌用 `Text1..Text4` 的 chunk。

### M1.4 — `mcmt doctor`（2026-08-17）✅（形狀分佈由 M5.6 補齊）

`src/mcmt/doctor.py`（統計）+ `src/mcmt/cli/`（組裝與格式化）+ 12 個測試。指令：`mcmt doctor <世界資料夾>`，離開碼 0 可處理 / 1 拒絕 / 2 路徑有問題。

- 逐 region 檔、逐 chunk 串流，峰值記憶體是單一 chunk。region header 壞掉時記錄並中止那一張，**掃描繼續**。
- **「唯讀」有測試擋著**：比對掃描前後世界資料夾內每個檔案的 mtime 與大小。
- 掃描範圍是所有名為 `region` 的目錄（含 `DIM-1`/`DIM1`/datapack 自訂維度）。`entities/` 與 `poi/` 不算方塊 chunk，v1 不看。

~~未做：節點形狀分佈~~ → **M5.6 已補上**。doctor 自己不判斷形狀，只把嗅探器與掃描層的答案數起來。

真實世界實跑：

| 世界 | 規模 | 時間 | 結果 |
|---|---|---|---|
| 100 Ways To Die | 13 region / 6,465 chunk | 2 秒 | 通過（DV 4325 佔 96.9%） |
| Minecraft Party 2 | 5 維度 / 406 region / **207,515 chunk** | **93 秒** | 通過（DV 3955 43.5% · 4438 43.1% · 4556 13.3%） |
| Find The Button No Cakewalk | 142 region / 36,459 chunk | 未計時 | **拒絕**（852 `level_wrapper` + 15 `legacy_sign_text`） |

MP2 的 DataVersion 分佈證實 **per-chunk 世代分派不是理論問題**：兩個世代各佔 43%。
93 秒的瓶頸是「每個 chunk 都完整解析 NBT」——目前只為了讀 `DataVersion` 與結構檢查。真要加速就是寫一個只挖需要欄位的淺解析器，但那是最佳化，不是現在該做的事。

### M2 — 安全層（2026-08-17）✅

五個任務五個 commit，其中兩個是 `safety/` 的獨立 commit。共 127 個測試通過。

**M2.1 路徑圍籬** `safety/paths.py`
- sandbox 根 = `<專案根>/sandbox`（往上找 `.git`/`pyproject.toml`），找不到才退回 `<CWD>/sandbox`。從 `src/` 或 `tests/` 底下跑都指向同一個沙箱。
- `.minecraft` 檢查**優先於** sandbox 檢查。比對的不是字面 `.minecraft/saves`，而是「有 `.minecraft` 成分且其後有 `saves` 成分」——語料就在 `.minecraft\versions\1.21.10\saves`。
- `ReadOnlyPath` **刻意不實作 `__fspath__`**：`open(p,"w")` 會 TypeError，`shutil.copy` 也拿不到它。
- **連結逃逸是真的走得通的**：這台機器不給建 symlink（WinError 1314），但 `mklink /J` 的目錄連接點不需要管理員權限，`resolve()` 一樣穿過去。測試 symlink 失敗就退回 junction，不整條跳過。

**M2.2 世界指紋** `fingerprint.py` — blake2b 掃「region 相對路徑 + chunk index + 原始壓縮 payload」。不餵磁區排列、chunk 時間戳、mtime/大小（合約明文禁止 mtime）。壞掉的 region 折成穩定標記而不拋錯——指紋負責身分，健檢是 doctor 的事。

**M2.3 `mcmt sandbox import`** `sandbox.py` — 逐檔 `ensure_readable` 讀 → 逐檔 `ensure_writable` 寫，不是 `shutil.copytree`：**每一個寫入都經過圍籬**。`.mcmt-origin.json` 記來源絕對路徑、匯入時間、**來源的**指紋。目標已存在要 `--replace`；目標落在來源底下直接拒絕。

**M2.4 `BackupSet`** `safety/backup.py` — 備份放 `sandbox/.mcmt-backups/<世界>/<時間戳>/`，與世界資料夾**平行**，世界資料夾不會多出任何檔案。重複 `protect` 不重複備份（重複備份會用已改壞的內容蓋掉原始備份，那比沒有備份更糟）。protect 一個還不存在的檔案是合法的，回滾時刪掉它。還原逐檔進行、失敗的收集起來繼續，訊息含備份目錄絕對路徑並 `from` 原始例外。

**M2.5 讀取入口接上圍籬** — **高階函式收使用者路徑**（`survey_world`/`world_fingerprint`，入口呼叫一次 `ensure_readable`）；**低階只收 `ReadOnlyPath`**（`read_region`，裸 `Path` 直接 TypeError）。`nbtio/` 因此 import `safety/paths.py`——沒有環，例外與理由記在 `docs/ownership.md`。

真實資料驗證（工具第一次真的寫東西）：`sandbox import` 「100 Ways To Die」95 MB / 1,775 檔 / 12 秒，逐位元組比對 **1,775/1,775 相同**，副本只多出 `.mcmt-origin.json`，副本指紋與 origin 記的來源指紋一致。

> `sandbox/100 Ways To Die/` 現在有一份 95 MB 的真實世界副本（已 gitignore），M3/M4 要驗證 region 寫入時可以直接用。不需要了就整個資料夾刪掉。

### M3 — nbtio 完整（2026-08-17）✅

三個任務三個 commit（外加一個 fixture 更換）。178 個測試通過，其中 9 個是碰真實檔案的整合測試。

**M3.1 region 寫入** `write_region` + `ChunkWrite` + `RegionWriteReport`
- 介面讓「這個 chunk 有沒有被改過」在呼叫端**看得見**：`ChunkWrite.unchanged()` / `.replaced()` 兩個建構子，不是一個讓人隨手填的旗標。`unchanged` 只能從 `RawChunk` 建，帶著磁碟上的原始壓縮位元組與原始 timestamp。
- **這一層永遠不壓縮任何東西。** payload 一律是已壓縮好的位元組。L2「重新壓縮後位元組一致」是巧合，寫入層不依賴它。
- 先寫 `.mcmt-tmp` 再 `os.replace`：寫到一半掛掉時原檔完好無損。
- 真實資料：讀進來寫回去，**檔案位元組與 fixture 完全一致**；改一個 chunk，其餘 29 個 payload 與 timestamp 全部原樣；整個世界（13 region / 6,465 chunk）round-trip **6,465/6,465 位元組一致**。
- 那次全世界跑抓到一個真 bug：目標檔不存在時 `size_before` 是 0，`realigned` 因此恆為 true，13 張全被報成磁區重整。**警告出現在不需要它的地方，使用者就會學會忽略它。**已修。

**M3.2 `datfile.py`** — `level.dat` 讀寫。**這裡沒有外科式寫入這回事**：region 是 1024 份獨立文件，`level.dat` 是一份，改一個欄位就得整份重編。保證只到 L1（解析→序列化位元組一致），已在真實 `level.dat`（7,271 bytes NBT）上實測成立。壓縮形式讀什麼寫什麼（不順手升級成 gzip）；gzip `mtime` 固定 0（否則同內容每次位元組都不同）。

**M3.3 損壞防禦** — 補兩個 M1.2 沒處理的類別：**磁區重疊**（讀；兩邊都讀得出東西，不檢查就安靜地讀到垃圾）與**寫入端輸入驗證**（重複 index、index 超範圍、非法壓縮類型、空 payload）。重複 index 特別陰險——其中一筆會變成指不到的孤兒磁區，而檔案看起來還是合法的。驗證在動磁碟之前做完。

**測試 fixture 的授權考量**：`tests/fixtures/` 底下的真實資料一律取自 `TT_WORLD_NAME_PROBE`（本專案自建的探測世界），**不用語料地圖**——那些是別人做的冒險地圖，放進要公開發布的 GPLv3 repo 等於重新散布別人的作品。`level.dat` fixture 另外移除了 `Player`（玩家 UUID 與座標）與 `WorldGenSettings`（種子）。

---

### M4 — legacy 寫入驗證（2026-08-17，`[遊戲實測]`）✅

**legacy 寫入路線成立**：DV **3700** 的 chunk 裡以舊式 JSON 字串寫入自訂命名空間 translate key，1.21.11 由世界 `resources.zip` 解出並顯示中文。`write/legacy.py` 的設計前提不必改。

程序與兩輪測試的細節見 `docs/m4-checklist.md`，完整記錄見 `SPIKE_RESULT.md`「M4 遊戲實測」。**四項不能重推的結論**：

1. **DataFixer 確實解析 DV < 4325 chunk 裡的舊式 JSON**，而且**存回磁碟時就地轉成原生 compound**——`{"text":…}` 與純量都變成 **`{"": …}` 空鍵形式**。`empty_key_compound` 不是某個工具的怪癖，是 Mojang `NbtOps` 的標準輸出。
2. **4325 分水嶺由對照實驗確立**：同一個 `'""'`，native chunk 顯示字面引號（M0-4）、3700 chunk 顯示空白。同一份輸入只差 DataVersion，結果相反。
3. **遊戲會升級玩家走過的 chunk**：開一次世界後，同一張 region 的 953 個 chunk 有 144 個 3700→4671、809 個不動。**「同一世界兩套世代並存」是使用者玩過就會發生的事**，不是 1.12 舊地圖專屬，也不是我們造成的。→ **extract 當下嗅探的 `encoding` 會因為使用者中間玩過一次而失效**；`world_fingerprint` 抓得到，M11 的 `expected_encoding` 守門是這個情境的唯一防線。
4. **世界資源包的 `pack_format` 有下限，修正了 M0-5**：地圖自帶的 `pack_format: 22` 被 1.21.11 拒絕（「無法套用伺服器資源包」），換成 75 + `supported_formats` 就正常。→ **M10 的硬需求**：合併進地圖既有的舊 pack 時**不能只加 lang 檔**，必須同時處理 `pack.mcmeta`，否則整個 pack 被拒、譯文一起陪葬；而那是在改地圖自己的檔案，要在報告中明確告知使用者。

---

### M5 — model + 掃描 + 建樹（2026-08-21）✅

| 任務 | 狀態 |
|---|---|
| M5.1 `model/component.py` 形狀嗅探 | ✅ |
| M5.2 `model/generation.py` | ✅ |
| M5.3 `model/segments.py` 攤平與段落 | ✅ |
| M5.4 `model/node.py` 節點路徑 | ✅ |
| M5.5 `scan/sources/region.py` | ✅（告示牌 + CustomName；廣度留給 M13） |
| M5.6 doctor 接上形狀分佈 | ✅ |
| M5.7 四個 codec（`tree/codecs/`） | ✅ |

**與合約綁死的做法**：`model/` 的三個模組都有一條測試**直接讀 `docs/contracts/*.json`**
比對 enum（`Encoding`、`Codec`）與 `SCHEMA_VERSION`。所以這幾個 commit **沒有 bump
`SCHEMA_VERSION`**——沒有任何合約欄位被新增、移除或重新定義，而版本號 +1 只會讓現有
產物作廢卻不告訴任何人哪裡不一樣。要漂移得同時改兩邊，那正是合約改動流程想擋的事。

**真實資料驗證**（每一項都在跑完之後才算完成）：

- 嗅探器**重現了第二輪 probe 的數字**：MP2 的 `json_empty_quoted` 2,340、
  `json_string_object` 110，且都在 DV 4556。
- 攤平器跑 MP2 的 5,344 棵樹，**失敗 0**，最大巢狀深度 3（與 probe 一致）。
- `doctor` 現在會報：MP2 57,192 個文字節點，其中 **4,473 個是「新世代 chunk 裡的
  舊式 JSON」會被跳過不翻**，並在報告裡說明理由。

**兩個真實資料抓到的修正**（都寫回 `SPIKE_RESULT.md`）：

1. **前導引號不算 JSON 證據**。`100 Ways To Die` 有一行告示牌是 `"looks like you`
   ——跨行的英文引述。原本會被判成解析失敗而跳過。改成「前導引號必須解析成功才算
   `json_string_scalar`」；`{` 與 `[` 維持保守。
2. **`with` 不攤平、只原樣帶走**。MP2 的節點有 translate 參數，內容是玩家名與分數
   這類執行期產物——翻它沒意義，弄丟它會讓重建時整個參數消失。

**M5.2 與 M5.7 的重點**：

- `generation.py` **刻意不提供任何形狀相關的函式**，而且有測試守著（掃過公開名稱，出現含 encoding/shape 的名字就失敗）。`write_back_version()` 回傳它收到的版本號——「永不升級」寫成函式而不是註解。
- **每個 codec 都要回答 `faithful_round_trip`**。`json_component` 忠實（真實資料 78/78，compact 形式）；**`snbt` 不忠實**——`to_snbt()` 會把鍵排序，所以 SNBT 不能整份重編，只能用 `span` 位移替換。那正是合約裡 `decode.span` 與「由後往前」存在的理由。
- `command` codec **明確拒絕**（`NotImplementedError`）：指令語法解析是最難估的一項，而掃描層根本還不去找 `Command` 欄位，留一個猜著做的實作等於等著某天寫壞別人的指令方塊。
- `lang_json` 的「寬容」被真實資料打了一次臉：初版用正則，MP2 的 5 個語言檔 **0/5** 通過（註解裡有雙引號、BOM、註解裡有冒號逗號）。改成會追蹤字串狀態的掃描器後 **5/5，讀出 50,959 個 key**。

**兩件留給後面里程碑的判斷**：

- **可塌縮只有 20%**（MP2 5,344 棵樹裡 1,066 棵）。不可塌縮的主因是 `click_event`
  （1,694 個互動告示牌，§ 碼表達不了，非塌縮不可）與 `translate`（2,045 個）。
  後者是**合約的規範文字與它自己的 sample 互相矛盾**的地方：規範說 false 只給
  「nested translate」，sample 卻把根節點標 false、巢狀標 true。目前採**保守解讀**
  （任何 translate 都不可塌縮），代價是「重建整棵樹」變成常態路徑。M10/M11 開工前
  要定案。
- **MP2 有自己的中文化系統**（5 個語言檔 + `mcp.*` key）。翻它的 `{translate:"mcp.X"}`
  節點等於覆蓋地圖作者自己的在地化；更合理的可能是翻它的 lang 檔。M6 denylist 或
  M13 要處理。

---

### M6 — 規則引擎（2026-08-21）✅

不動點迭代，上限 32、超限拋錯並列出最後一輪新增的標籤。**兩條硬性要求都不是靠自律**：
順序無關是因為每輪跑完所有規則再取聯集（規則只加標籤、不刪標籤）；不靜默停止是因為
「有時候少抽幾個節點」是最難查的 bug。

denylist 用 `deny:<原因>` → `do_not_translate` 兩段式，結論的定義只有一處。

**回歸測試刻意不走正式掃描層**——掃描層現在只找告示牌與 CustomName，拿它驗 denylist
會通過但什麼都沒驗到。改成走過 chunk 裡每一個字串節點問規則引擎。M13 掃描廣度補齊後
第一道防線會消失，那時這條測試已經在守著。

**它立刻抓到兩個逐條列舉想不到的漏洞**：`biomes.palette` 是**字串 list 不是 compound**，
所以 `("palette","Name")` 完全認不到（MP2 有 456 萬個）；`Status` 與 `id` 也是識別碼。
因此改成「`sections` 底下整段擋掉」——**列舉已知陷阱漏掉的東西你不會知道，圈出已知
安全區漏掉的東西會馬上炸在臉上。**

MP2 全掃 12,262,582 個字串節點、96% 被擋、**0 漏**。

### M7 — `mcmt extract`（2026-08-21）✅

`extract/keys.py` · `placeholders.py` · `build.py` · `emit.py` + `cli/extract.py`。

- **key**：`discriminator` 在 `unit_id` 與 `translateKey` 裡是同一個字串，由同一個函式產生一次。三種格式都與合約的 regex 綁死。`normalize` 只做 NFC 與換行統一，**不碰空白**（告示牌用前導空白置中）。碰撞走 `_1` 並把兩邊 hash 輸入記進 `keymap.json`。
- **佔位符**：多重集合完全一致才過，**hard fail**。順序可不同；「全數前移」單獨警告（判準是標記彼此相鄰，不是在字串開頭）。空 target 回報 `empty_translation` 而不是佔位符錯誤。
- **`build.py` 不自己判斷任何一件事**——形狀問嗅探器、世代問 `generation`、該不該翻問規則引擎、攤平問 `segments`。
- **最重要的測試是「產出的文件真的通過 schema 驗證」**，而且真實產出也驗過：`Arena of Darkness` 的 13 MB `extract.json` 0 錯誤。

真實地圖：

| 世界 | chunk | 文字節點 | 翻譯單位 | 出現次數 | 時間 |
|---|---:|---:|---:|---:|---:|
| 100 Ways To Die | 6,465 | 8,315 | **937**（M13a 後修正為 936，見下方 M13a 節） | 1,691 | 2 秒 |
| Arena of Darkness | 88,969 | 15,563 | **607** | 10,421 | 31 秒 |

**去重省下的量才是這個工作流的重點**：Arena of Darkness 的譯者要打 607 條，不是 10,421 條。

> 一個真實觀察：Arena of Darkness 有一個 `block_entity_name` 是 `'@'`，**出現 9,491 次**。
> 那多半是地圖的紅石／指令系統用來找容器的名字，翻了會壞。待翻檔的 `note` 會寫「出現
> 9491 次」，人看到這個數字自然會停下來想一下——這正是「工具不介入、但把該看到的資訊
> 攤在眼前」的實例（見上方「不做術語表」那節）。

---

### M10 — resourcepack 後端（2026-08-21）✅

| 任務 | 重點 |
|---|---|
| M10.1 `lang.py` | **樣式跟著文字走，不跟著位置走**——譯者調換語序時，第一版照段落序號輸出，把譯者寫的順序改回去了 |
| M10.2 `pack.py` | 合併既有 pack，**只加 `supported_formats`、不改它宣告的 `pack_format`**（M4-5 的教訓） |
| M10.3 `backend.py` | editplan：後端決定**值是什麼**，寫入層決定**怎麼安全地放進去** |

另外兩個順序細節：§ 的顏色碼會重設格式，所以顏色必須寫在格式之前；轉義還原要在殘留
檢查**之後**做。

寫 M10.1 時發現並修掉 `segments.py` 的一個錯誤：**§ 碼只能開啟樣式，沒有關閉的方向**。
`{"italic": false}`（壓掉物品名預設斜體的慣用法）因此不可塌縮。

### M11 — 寫入層（2026-08-21）✅

三個 `write/` 獨立 commit。**不對稱終於可以講得很具體**：

| | legacy chunk（DV < 4325） | native chunk（DV ≥ 4325） |
|---|---|---|
| 寫什麼 | JSON 字串（[遊戲實測 M4-1]） | NBT compound（[遊戲實測 M0-3]） |
| list | 型別不變，**不必提升** | String list 塞不進 compound，**非提升不可** |

所以「不要用一套邏輯硬套」不是風格偏好——一邊完全不必提升，另一邊非提升不可，
用 if/else 藏起來就是等著某天套錯邊。

**真實世界的完整來回**（自建探測世界，3,599 chunk）：

```
計畫 10 個節點 → 寫入 9 個
改動 1 個 chunk，原封複製 929 個
NBT list 提升 2 次
磁區重整 3,821,568 → 3,817,472 bytes（有報告）
```

逐項驗證：930 個 chunk 只有 chunk 0 的 payload 變了、**929/929 未改動的 chunk 連
timestamp 都一樣**、探測世界原本就有的 `block.minecraft.diamond_block` 節點沒被碰、
`resources.zip` 有 lang 檔。`--dry-run` 完全不碰存檔並產出 `editplan.json`。

### M11 遊戲實測（2026-08-21）：**整條鏈成立** ✅

把翻好的 `sandbox/roundtrip` 拿進 1.21.11，三項 `[遊戲實測]`：

**① 端到端成立。** 告示牌全部顯示中文。這是「尚待驗證」表首列、標為**高**的那一項
——M0 證明的是「手動注入 + 資源包」那半段，這次**中間沒有人下過任何一個 `/data` 指令**。
同 chunk 裡本來就有的 `block.minecraft.diamond_block` 照常顯示，**沒有誤傷**。

**② 吊掛告示牌比一般告示牌窄很多。** 7 個 CJK 字（`吊牌正面第一行`）被截掉，同樣長度
在一般告示牌上完全正常。目前給它的 60px 預算**仍偏寬**。→ 這是 M8 的第一個真實資料點。

**③ `CustomName` 在 native chunk 不解析任何形狀。** 寫 SNBT（`{translate:"…"}`）進去，
GUI 標題顯示**字面文字**。行為與 M0-3 的告示牌 `messages` 完全一致。
→ **native 的 `block_entity_name` 只能走 `in_place`**（直接把譯文寫進節點），和
`LevelName`、書名、作者、草稿書頁同組。

> 原本的推測（探測世界的裸字串既是合法 SNBT 也是合法折疊 component，所以 CustomName
> 應該是 component 的 SNBT）**被推翻**，理由記在 `SPIKE_RESULT.md`。

> **一個誠實的缺口：`CustomName` 目前拒寫。** [實測] 它在兩個世代都是 String 節點
> ——native（DV 4671）是裸字串、legacy（DV 3700）是 JSON 純量 `'"@"'`。要放
> translate key 進去，native 那邊該寫什麼形狀**沒有實測依據**：寫 compound 會改掉
> 欄位的 NBT 型別，寫 JSON 字串又踩到 M0-3。已列入 `SPIKE_RESULT.md` 尚待驗證，
> 標為高——**`Arena of Darkness` 有 9,579 個這種節點**。

---

### `CustomName` 改走 `in_place`（2026-08-21）✅

[遊戲實測 M11-3] 已經給出答案，所以這一項不必再進遊戲。四個 commit（合約／model／
extract／`write/` 各一，後兩者是規範要求的獨立 commit）：

| 層 | 做了什麼 |
|---|---|
| 合約 | `SCHEMA_VERSION` 4 → 5。`block_entity_name` 加進「category ⇒ in_place」那條 if/then；`excluded.reason` 新增 `untested_write_shape`；`literal` 的語意收緊為**保留節點既有的 NBT 形狀** |
| `model/strategy.py` | category ⇒ strategy 的唯一權威。與合約的 if/then 由測試綁死 |
| `extract/` | legacy chunk 的 in_place 節點 per-occurrence 排除；不可塌縮的整個跳過並計數 |
| `write/in_place.py` | 新的第三條寫入路徑 |

**`write/in_place.py` 不是第三份 legacy/native 實作。** 那兩份的不對稱是**世代**的
（遊戲會不會跑 DataFixerUpper），而 in_place 完全不做那個判斷——它**什麼形狀都不選**，
保留節點原本的形狀只換裡面的字。分派依據因此是 `encoding` 不是 `data_version`。

有依據的形狀只有四個（`bare_string` / `plain_string` / `text_compound` /
`empty_key_compound`），其餘一律拒寫並進報告。**不把 `TAG_String` 提升成 compound**
（告示牌那邊整個 list 提升過，`CustomName` 沒有那條退路），**兩種 compound 形式互不
正規化**（路過的 `{"": …}` 順手改成 `{"text": …}` 就是重新編碼一個沒被要求改的欄位）。

順手抓到 backend 的兩個 bug——in_place 之前沒有任何 category 走得到，所以一直沒被觸發：
`_value_for` 回傳的是**原文**不是譯文（會是一次沒有效果卻看起來完全成功的存檔修改），
而 in_place 的 unit 也被塞進 lang 檔、`key` 是 null 於是寫成字面的 `"None"` 鍵。

真實資料：探測世界的兩個 CustomName 正確寫成 `StringTag` 譯文、沒進 lang 檔、929 個
chunk 原封複製。**但 `Arena of Darkness` 一個都寫不出去**——見下方 B。

### M8 字寬的表與工具（2026-08-21）✅（量測見下面那節）

`mcmt/width.py` + `mcmt/fontdata/vanilla_v1.json` + `tools/calibrate_font_widths.py`
+ `docs/m8-checklist.md`。

**數字放在資料裡不放在程式裡**：校準是「改資料」，`--record` 只重寫那一個 JSON，
「哪些量過、哪些還是猜的」永遠只有一個地方要看。`emit.py` 原本自己有一份
`_WIDTH_BUDGET`，已刪掉——兩份數字就會有一天只校準了其中一份。

**note 從「寬度上限 90px」改成「約 10 個中文字」。** px 對譯者沒有意義，字數有。

`enforcement` 判準是資料裡的 `calibrated` 旗標（當時全部是 `warn`，量測完成後自動
升成 `error`）。一條測試把 [遊戲實測 M11-2] 變成會紅的東西：數字必須預測得出
「6 個 CJK 進得去、7 個進不去」——後來的量測證實它一直是對的。

校準工具**產生方式是改寫你放好的空白告示牌，不是生成 `/setblock`**——這個工具從來
不碰方塊，要它生成 setblock 就得猜 1.21.11 的方塊實體 NBT 語法，猜錯的症狀是「進遊戲
什麼都沒出現」，白跑一趟。做法沿用 `tools/m4_prepare.py`。

### M12 自動化端到端（2026-08-21）✅

`tests/integration/test_end_to_end.py`，19 條。走使用者真的會走的四步，fixture 是
自建探測世界的 30-chunk 切片（剛好同時有告示牌與 CustomName，**兩條寫入路徑一趟都
走到**）。

**它立刻抓到一個真 bug**：`apply_report.assets_installed` 一直是 `["resources.zip"]`，
而合約要的是物件陣列。單元測試驗的是手寫的 sample fixture，驗不到「程式真的會吐出來
的東西」。

**一個值得記住的發現**：「未觸碰的 chunk 位元組一致」這條**單獨不夠**。用突變確認過
——把 apply 改成每個 chunk 都解碼再編碼，那條測試**仍然是綠的**，正是 `SPIKE_RESULT`
的 L2 那個巧合。抓得到的是 **timestamp**：`ChunkWrite.unchanged` 帶原始時間戳、
`replaced` 蓋當下時間，所以「有沒有走原封複製那條路」在磁碟上留得下痕跡，位元組留不下。

---

### M8 校準完成 + legacy `CustomName`（2026-08-21，`[遊戲實測]`）✅

一次進遊戲做完兩件事，兩件都成立。完整記錄見 `SPIKE_RESULT.md`「M8 + legacy
CustomName 遊戲實測」，這裡只留不能重推的結論。

**① 字寬：四個數字全部命中校準前的猜測。**

| | ASCII（`M`） | CJK（`中`） | 預算 |
|---|---|---|---|
| 一般告示牌 | 15 | 10 | **90px（約 10 個中文字）** |
| 吊掛告示牌 | 10 | 6 | **60px（約 6 個中文字）** |

CJK 9px、粗體 +1（吊掛上 10 個粗體 `M` 只顯示 8 個——若粗體不加寬就會全部顯示）。
所以 [遊戲實測 M11-2]「7 個 CJK 字被截掉」不是碰巧對上，`hanging_sign` 從 `[待驗]`
升成 `[遊戲實測]`。

> **階梯定的是比例，不是絕對 px。** 窮舉過所有相容的參數組，全部是等比族
> （ASCII : CJK 恆為 2 : 3），整張表乘以 2 也一樣相容。絕對尺度靠「ASCII = 6px」
> 這個 `[文件]` 級的錨。不影響工具——真正用到的 `cjk_capacity` 只依賴比值。

**`enforcement` 因此升成 `error`，而且現在真的會擋**（`overflow_rejected`，合約本來
就有這個原因）。合約寫的是「拒絕該筆譯文」，校準前一律 warn 是因為「拿沒驗過的預算
去擋會退掉正確的譯文」；驗過了就得執行，否則那個欄位在說謊。

**一個豁免**：原文本身就放不下時，只要譯文不比原文寬就放行。那是地圖自己的排版，
在那種節點上退掉一個「不比原文糟」的譯文，等於要求譯者解一個原作者沒解的問題，
而且無論他怎麼寫都過不了。

**② legacy `CustomName`：JSON 兩種都成立，裸字串會弄丟名字。**

| 變體 | 結果 |
|---|---|
| `'"譯文"'`（JSON 純量） | 正確顯示 |
| `'{"translate":…}'`（JSON 物件） | 正確解出資源包的譯文 |
| `'譯文'`（非 JSON 裸字串） | **顯示原版預設名——欄位整個被丟掉** |

**第三個是反面證據，而且比前兩個重要**：在舊世代換掉節點的形狀會**悄無聲息地弄丟
別人地圖上的名字**。「保留節點既有的形狀」在這裡不是保守，是唯一不會壞事的選擇。

落地：`write/in_place.py` 支援六種形狀（多了 `json_string_scalar` /
`json_string_object`），`extract` 的排除判準從**世代**改成**形狀有沒有實測依據**
（清單在 `model/strategy.py`，寫入層的實作與它由一個 assert 綁死）。

真實地圖：`Arena of Darkness` 的 CustomName occurrence 從 **9,579 全數排除** 變成
**9,581 個 0 排除**，並真的寫了一筆驗證（DV 3700 的旗幟，`'"Letter F"'` →
`'"測試譯文"'`，形狀與 DataVersion 都沒變，同 region 其餘 952 個 chunk 原封複製）。

> **B 成立代表舊世代可以走 translate key**（一份存檔支援多語言）。v1 不走：
> `strategy` 是 per-unit 的，而同一段原文可能同時有 native 與 legacy 的 occurrence，
> native 那邊 translate key 不成立（M11-3）。留給 v2。

---

### M13a — 掃描廣度：物品與實體（2026-08-22）✅

八個任務八個 commit（分支 `m13a`，計畫見
`docs/superpowers/plans/2026-08-22-m13a-items-and-entities.md`，逐任務記錄在
`.superpowers/sdd/2026-08-22-m13a-items-and-entities/progress.md`）。

**`entities/*.mca` 確實一行寫入層都不必改**——它就是 region 格式（同一套 header、
同一套壓縮），`write_region` 直接可用。

**但物品暴露了 `apply.py` 的一個分派缺陷，最終 fix wave 才修掉。** 舊的
`_apply_edit` 只看 `node_path` 最後一步是 `key` 還是 `index`。在 M13a 之前那是對的
——v1 只掃告示牌（index + translate key）與 `CustomName`（key + literal），剛好是
四種組合裡的兩種，所以「key ⇒ in_place、index ⇒ translate key」碰巧成立。M13a 把
另外兩種也掃了進來，等價關係就假了：

| 組合 | 例子 | M13a 開工時的行為 |
|---|---|---|
| index + literal | 舊格式草稿書頁 `tag/pages/[i]` | **寫成 JSON 字串，弄壞存檔**（AoD 9 筆） |
| key + translate | 物品 `custom_name` / `item_name`、`entity_name`、`text_display`、新格式 `pages[].raw` | 全數拒寫（AoD 3,788、100WTD 364） |

真正的判準是 `edit["value"]["kind"]`，不是路徑形狀。已修（兩個 write/ 獨立 commit），
真實地圖重驗：AoD 14,285 筆 edit 全寫成、`unwritten` 0 筆。

| 任務 | 產出 |
|---|---|
| T1 | `datfile.py` 驗證修正（`_verify` 死碼 bug，review 抓到） |
| T2 | denylist 補新版命名空間鍵名（`minecraft:can_break` 等）+ 真實地圖驗證 |
| T3 | `entities_files(world)`（`nbtio/region.py`），fingerprint 涵蓋 `entities/` |
| T4 | `scan/registry.py` 來源清單抽象（純重構，region 一個來源） |
| T5/T6 | `scan/sources/item.py`：`components`（1.20.5+）與 `tag`（舊格式）雙形狀白名單，容器/收納袋/成書/草稿書遞迴 |
| T7 | 接上 `region.py` 的 `Items[]`/`Book`；順手修 `fontdata/vanilla_v1.json` 的 `book_page.wrap` 從非法值 `"soft"` 改成 `"auto"`（M8 遺留，schema 從沒驗過它，掃到 book_page 才炸開） |
| T8 | `scan/sources/entities.py`：`CustomName`/`text_display`/`Passengers[]` 遞迴/裝備物品，**證明 `entities/*.mca` 走同一條外科式寫入路徑不必改** |

**兩個計畫層級的 bug 被 review 抓到**（連同 M13a 之前的五個，累計七個）：T4 的
`chunks = list(read_region(path))` 會讓串流搶救退化成全有全無（已修，用 try 包住整個
for 迴圈）；T6 的 `_OLD_CONTAINER_KEYS` 漏了 spec 明列的 `ChargedProjectiles`（已補）。
T8 的 brief 抄了同一個 `list()` 反模式，**這次在 review 之前就發現並改掉**，實作採用
與 T4 修正後一致的串流寫法。

**真實地圖最終數字**（M13a 全部接上後，`mcmt extract --lang zh_tw`）：

| | Arena of Darkness | 100 Ways To Die |
|---|---:|---:|
| chunk | 88,969 | 6,465 |
| 文字節點 | 19,903 | 9,039 |
| 翻譯單位 | **902** | **1,348** |
| custom_name | 141 | 21 |
| entity_name | 54 | 11 |
| text_display | 40 | 160 |
| book_page/title/author | 45 | 179 |
| sign/hanging_sign | 587 | 933 |

與清點的相異數對照都在「小幅出入」範圍內（攤平會合併或拆開部分節點），**沒有出現
「抽太多/抽太少」的方向性訊號**，白名單與 denylist 判斷為正確。

**修正一個過期數字**：`docs/STATUS.md`（M7 那節）先前寫「100 Ways To Die 937 個
翻譯單位」，那是 M7 當時（`CustomName` 改走 `in_place` 之前）的數字。`in_place` 落地
後，帶 `extra` 樹的 `CustomName` 節點會計進
`stats.skipped_non_collapsible_in_place`（`in_place` 沒有「每段一個 key」的位置，
與「不可塌縮 ⇒ 每段一個 key」的規則互斥），**M13a 開工前**（region 來源尚未接上
物品與實體掃描）是 **936**，差的 1 個已計數、有報告，不是靜默漏掉。M13a 全部接上後
是 1,348（見上表），那是現在的數字。

已知缺口（見各任務 review 的 deferred minors，累計進下面「已知缺口」）：
`minecraft:use_remainder` 等內嵌單一 ItemStack 的組件未列白名單、
`filtered`（聊天過濾）文字未抽（語料 0 樣本，且屬寫入層該同步 key 的事）、
`EntityTag`（生怪蛋具名實體）新舊格式都未涵蓋、`json_string_array` 的 `in_place`
仍拒寫。全部是「漏抽看得見」方向，不是「誤翻看不見」方向。

---

### M13b — 掃描廣度：`level.dat`／`scoreboard.dat`／datapack（2026-08-22）✅

八個任務八個 commit（分支 `m13b`，計畫見
`.superpowers/sdd/2026-08-22-m13b-datfile-and-datapack/`）。M13a 做完了
M13.0–M13.4，這一輪做完 M13.5–M13.9：

| 任務 | 產出 |
|---|---|
| T1 | `write/common.py`：節點編輯引擎（`apply_edit_to_compound`）從 `write/apply.py` 搬出來，`apply.py` 改用顯式 `kind → writer` 分派表（**M13a 遺留、spec 明文要求的重構**） |
| T2 | `write/datfile_apply.py`：`.dat` 檔通用寫入器（整份重新編碼，`level.dat` 與 `scoreboard.dat` 共用） |
| T3 | `scan/sources/level_dat.py`：`LevelName`（in_place）／`CustomBossEvents.<id>.Name`（translate key）／`Player.Inventory[]`（走 `scan_item`） |
| T4 | `scan/sources/scoreboard.py`：`Objectives[].DisplayName`／`Teams[].DisplayName`／`Teams[].MemberNamePrefix`／`MemberNameSuffix` |
| T5/T6 | `scan/sources/datapack.py` + `write/datapack_apply.py`：advancement JSON 的 `display.title`／`display.description`，資料夾與 zip 兩種形式、單複數目錄名都認 |
| T7 | 已在地化節點整個跳過（樹裡任何一處有 `translate` 就跳過，避免蓋掉地圖自己的多語言支援） |
| T8 | 端到端測試擴充 + 兩張語料地圖真實驗證 + 文件寫回（本節） |

**T8 的端到端測試立刻抓到一個真 bug，已修（獨立 commit，理由詳述在 commit
訊息裡）**：`extract/build.py` 對 `level_name` category 把 `occurrence.encoding`
覆寫成 `plain_string`（欄位決定的形狀，避免世界名剛好以 `{`/`"`/`[` 開頭被
`sniff()` 誤判成 JSON）。但 `sniff()` 本身**永遠不會**回報 `plain_string`——
一個裸字串節點永遠回報 `bare_string`。`write/common.py` 的 `_guarded_encoding`
修好之前直接比對字串相等，於是每一筆 `level_name` 的 edit 在守門這關就被拒寫
成 `node_changed`，**`LevelName` 事實上整個寫不出去**，而這條路徑此前只被
單元測試用 `expected_encoding="bare_string"` 繞過，從沒被真正的
`extract → apply` 來回測到。這正是 M13a 教訓那句話（「複製了一段在舊脈絡下
正確的程式碼，而它依賴的不變式在範圍擴大之後靜默失效」）的第三次重演——這次
是「單元測試用了一個和真實 extract 產出不一致的 fixture 值」。

**真實地圖驗證**（`mcmt extract --lang zh_tw`，相異單位數）：

| category | Arena of Darkness | 100 Ways To Die |
|---|---:|---:|
| `level_name` | 1 | 1 |
| `bossbar` | 26 | 2 |
| `objective` | 168 | 156 |
| `team` | 17 | 13 |
| `team_affix` | 0（實際內容全空） | 0（欄位不存在） |
| `advancement_title` | 28 | 0（沒有 datapack） |
| `advancement_description` | 26 | 0（沒有 datapack） |

全部落在計畫開頭期望表的範圍內，沒有任何分類是「該非 0 卻是 0」。`--dry-run`
確認 `editplan.json` 裡三個新 `container.kind`（`level_dat`／`scoreboard_dat`／
`datapack_file`）都產得出真正的 edit。

**T7「已在地化整個跳過」的實跑代價**（2026-08-23，最終 review 修正時量的）：

| | Arena of Darkness | 100 Ways To Die |
|---|---:|---:|
| `skipped_already_localised` | **5** | **0** |

也就是這條規則在這兩張地圖上幾乎不花成本——它保護的是 MP2 那種**自己帶一整套
中文化系統**的地圖（[實測] 50,959 個 lang 值），那張還沒用 M13b 之後的掃描跑過。
順帶一提，這條規則把 CLAUDE.md 與 `model/segments.py` 用了整個專案的那棵示範樹
（`{"translate":"mcp.Cost_", …}`）從「攤平後翻譯」變成「整棵跳過」，兩份文件都
已按「推翻前人結論要保留原文並說明」的規矩加了註記，沒有直接改掉。

已知缺口（新增，見下方「已知缺口」清單）：`team_affix`／`scoreboard.dat` 的
legacy JSON 寫入路徑都只做到 `[實測]`（CLI 抽出來的真實數字），**沒有**
`[遊戲實測]`——兩張地圖的內容都不足以驅動這兩項的進遊戲驗證。

---

## 下一步

### M14 CLI／報告／文件

架構計畫裡這一項一直只有「CLI/報告/文件」六個字，2026-09-01 盤點過現狀，
寫成可以直接動手的清單：

1. ~~**`README.md` 嚴重過時，是這裡唯一確定要做的事。**~~ → **2026-09-01 完成。**
   整篇重寫成給第一次用這個工具的人看的：核心工作流圖、三條安全規則各一句、
   安裝、四個指令對照表、一段可照抄的最短可行路徑（import → doctor → extract →
   編輯 → dry-run → apply → 手動複製回去）、待翻檔欄位說明與 `[[n]]` 規則。
   「第三方」那節過時的 `anthropic`／`mcmt[llm]` 行一併刪掉。
2. **CLI `--help` 文字盤點過，已經相當完整**——四個指令、所有 flag 都有中文
   說明（`src/mcmt/cli/__main__.py`）。**這裡不用大改**，重寫 README 時可以
   直接沿用這裡的措辭以保持一致，不必重新想一套講法。
3. **人類可讀的報告輸出盤點過，也已經做得不錯**——`cli/apply.py` 的
   `format_apply()` 有完整的拒絕原因對照表 `_REASON_TEXT`（八種原因全部有
   中文解釋），`cli/doctor.py` 也已經印節點形狀分佈、跳過統計。**這裡目前
   沒發現具體缺口**；如果重寫 README 時對照著讀，發現措辭跟 CLI 實際印出來
   的不一致，才需要動這裡。
4. 不在 M14 範圍內、繼續維持原樣：已知缺口清單裡剩下的
   （`team_affix`／`scoreboard.dat` legacy JSON 寫入未進遊戲驗證、
   `book_page` 寬度未校準、`json_string_array` 的 `in_place` 仍拒寫）
   ——這些是功能缺口不是文件缺口，M14 做完不代表要連帶清掉它們。
   （datapack `.mcmeta` 過期 **2026-09-03 已處理**，見下方已知缺口清單。）

**建議順序**：~~先做 1（重寫 README），2、3 只在重寫過程中發現不一致才動。~~
1 已完成；2／3 對照 README 重讀過，措辭一致，未動。M14 剩下的只有第 4 項那批
功能缺口。

### 已知缺口（不急，但別忘了）

* ~~**`occurrence.raw_snapshot` 一直是 null……**~~ → **2026-08-31 已補**（三個獨立
  commit：extract 算出值 → editplan 帶上它 → write/ 的守門真的比對）。
  `_guarded_encoding()` 現在在形狀比對通過之後，`raw_snapshot` 不是 `None` 時再比對
  節點**現在**的字面值，抓到「形狀沒變但內容變了」（重放一份已套用過的舊 plan、或
  使用者在 extract 之後自己把節點的字改了）。`compound_tree` 永遠是 `None`（沒有
  單一字串能代表整棵樹）——`test_end_to_end.py` 把這個縮小後的殘留縫改寫成
  `test_a_compound_tree_replay_is_the_one_remaining_gap` 釘住，不再是整個
  shape-preserving 集合都是縫。SCHEMA_VERSION 5 → 6（editplan 新增必填的
  `raw_snapshot` 欄位）。
* ~~**`run_apply` 不比對世界指紋……**~~ → **2026-08-31 已補**：新增
  `WorldChangedSinceExtractError`（`SafetyError` 子類），`run_apply` 算出
  `fingerprint_before` 後立刻跟 `extract.json` 記的 `world_fingerprint` 比對，
  不一致就中止——`--dry-run` 也擋，理由與 `_check_binding()` 對 `extract_fingerprint`
  不看 dry_run 一致。這個檢查比逐節點的守門更粗但更早：連「這份 plan 完全不會碰到
  的節點被改了」這種 per-node 守門看不到的情況也擋得住。
* **`book_page` 的寬度還沒校準**（114px 是 `[文件]`）。v1 還沒掃到書本，所以連一個
  真實資料點都沒有；M13 掃到之後要照 `docs/m8-checklist.md` 再跑一次校準。
* **`json_string_array` 形狀的 `in_place` 仍拒寫**，沒測過。實務上罕見。
* ~~**MP2 還沒用 M13a 之後的掃描跑過。**~~ → **2026-09-01 已補**：doctor → extract →
  no-op 譯文 → 真實 `apply` → 還原 → doctor 覆核，全程無誤。3,072 筆 edit 全部
  寫入、0 筆拒寫，`skipped_already_localised` 擋下 3,515 筆真實地圖自帶的
  `mcp.*` 中文化條目。細節見 `SPIKE_RESULT.md`「M13a/M13b 之後 MP2 全掃」。
* ~~**`block_entity_name` 不被寫成 translate key，現在只剩上游一道防線……有一個
  一行的補強沒做**~~ → **2026-08-31 已補**：`backends/resourcepack/backend.py` 的
  `_value_for` 與 lang_pairs 收集改讀 `strategy_for(unit["category"])`，不再信任
  磁碟上 `extract.json` 裡可能被竄改的 `unit["strategy"]`。新增
  `test_an_in_place_edit_ignores_a_tampered_strategy_field` 釘住。乾淨的長期解仍是
  `edit` 加一個 `strategy` 欄位（合約改動），這裡只是把不變式拉回行程內。
* ~~**`write/in_place.py` 的模組 docstring 還把自己框成「保護 `CustomName` 的那個
  東西」**~~ → **2026-08-31 已補**：docstring 加一段說明主線防線在 F2 之後已上移到
  `strategy_for()`，這裡剩下的是防禦性兜底。獨立 commit（`write/` 目錄規範要求）。
* ~~**native 的 `minecraft:block_entity_data` 沒進物品白名單**~~ → **2026-08-31 已
  補**：`scan/sources/item.py` 的 `_scan_components` 比照舊格式 `BlockEntityTag` 補上
  這個 1.20.5+ 組件（`CustomName` → `block_entity_name`、`Items[]` 遞迴）。
* ~~**指紋的排序鍵用 OS 原生路徑字串**~~ → **2026-08-31 已補**：`region_files()` /
  `entities_files()` 的排序鍵改成 `str(p).replace("\\", "/")`。新增兩條測試在
  Windows 上真的建出會互撞的目錄名（`a/region` 與 `aX/region`）釘住排序與正規化後
  字串序一致。
* ~~**native 世界上的 list 提升會自撞……**~~ → **2026-08-31 已補**：
  `write/common.py` 新增 `apply_edits()` 批次入口取代逐筆呼叫
  `apply_edit_to_compound()`——同一個 list 的所有 edit 先分組，用「這次 apply
  開始前」的快照統一過守門，再依序寫入，讓守門不會被同批次裡另一筆 edit 剛造成
  的形狀變化污染。`apply.py`（region/entities）與 `datfile_apply.py`（`.dat`）
  兩個呼叫端都換成新入口；`datapack_apply.py` 的節點永遠以 key 結尾不受影響。
  新增 4 條回歸測試，其中一條確認「整個 list 被外部改過」這個 `TAG_List` 格式
  強制單一元素型別下唯一可能的外部改動形狀仍然正確整批拒寫。**真實地圖驗證**：
  `100 Ways To Die` 修前一次 apply 有 325 筆 `node_changed`（全部是告示牌），
  修後 2,420 筆 edit 全部寫成、0 筆 unwritten。
* **`team_affix`（`Teams[].MemberNamePrefix`/`MemberNameSuffix`）translate key 未單獨遊戲實測。**
  兩張語料地圖的實際內容全空，掃描與寫入路徑都已接上但從未真的寫過非空值進遊戲。
* **`scoreboard.dat` 的 legacy JSON 寫入路徑未單獨遊戲實測**——沿用 chunk 層級已驗證的
  `legacy.py`，但「DataFixerUpper 對 `.dat` 檔案一視同仁」這個推論本身沒有進遊戲確認過。
* ~~**datapack 的 `.mcmeta` 過期問題本計畫未處理。**~~ → **2026-09-03 已補**：
  Minecraft 26.2（pack_format 88）拒載 `supported_formats` 卡在 75 的 `resources.zip`
  之後，把同一個修法移植到 datapack。抽出 `src/mcmt/packmeta.py`
  的 `widen_supported_formats()`（`resources.zip` 與 datapack 共用、冪等），
  `write/datapack_apply.py` 在真的寫進某個 datapack 之後把它的 `pack.mcmeta`
  的 `supported_formats` 上限推到 `FORWARD_PACK_FORMAT`、下限維持它宣告值，
  資料夾與 zip 兩種形式都做，並以既有的 `pack_format_outdated` 警告回報。
  找不到 `pack.mcmeta` 靜默略過、讀不懂記警告但不中止。13 條新測試
  （`test_packmeta.py` 7 + `test_write_datapack_apply.py` 6），786 passed。
  兩個獨立 commit（`packmeta` 抽出／refactor 一個，`write/` 目錄規範要求另一個）。
* ~~**`world_fingerprint` 沒有涵蓋 `level.dat`／`data/scoreboard.dat`／
  `datapacks/**`……**~~ → **2026-08-31 已補**：這三個非 chunk 來源直接餵整份檔案的
  原始位元組進 digest（`level.dat`／`scoreboard.dat` 各一份，datapack 資料夾遞迴進
  每個檔案、zip 整份當一份檔案），排序鍵一併正規化成 `/`。6 條新測試涵蓋四種來源
  各自改動會變指紋、純 mtime 不會、三者都不存在時仍可正常算出指紋。
* ~~**`doctor` 的健檢範圍沒有涵蓋 `level.dat`／`scoreboard.dat`／datapack……**~~ →
  **2026-08-31 已補**：`survey_world()` 額外呼叫 `scan/sources/` 的
  `level_dat.scan`／`scoreboard.scan`／`datapack.scan`（跟 region/entities 那段一樣
  問掃描層本身），這三個來源掃到的節點併入既有的 `node_shapes`／`categories`／
  `legacy_json_in_native_chunk` 統計，新增 `skipped_level_dat` 等五個 `skipped_*`
  欄位。**這不是新的拒絕處理閘門**——extract 本來就把這三個來源的壞檔案當「跳過並
  計數」，doctor 只是把這個結果提前到不用跑一次 extract 就看得到。真實地圖驗證：
  Arena of Darkness 的 doctor 報告正確印出「datapack 進度檔：30 個」，與 extract 的
  既有數字對得上。
* ~~**〔command text 缺口 A〕`scan/command.py::_find_component` 不認命名空間組件鍵。**~~
  → **2026-10-14 已修**（`0b686f0`）：接受 `custom_name` 與 `minecraft:custom_name`；
  pinned 測試已改名 `test_a_give_commands_namespaced_custom_name_is_translated` 並反轉斷言，
  dispatch 組合補成 7 格（L2 在 entities、give 在 region，靠容器種類就分得開）。原描述：
  真實 1.20.5+ 語法是 `give @s minecraft:stone[minecraft:custom_name={...}]`，但
  `_find_component` 拿裸字串 `"custom_name"` 去比 `key=value` 的 `key`，命名空間形式
  永遠比不到，整條指令記進 `skipped_command_unsupported_shape`、一個字沒抽。
  **MP2 實測影響**：`give`/`item` 出現 4,565 次，其中 3,935 次帶
  `minecraft:custom_name=…` 全被跳過（去重後 8 個相異物品名）。Task 11 釘在
  `test_a_give_commands_namespaced_component_is_a_known_scan_gap`。修好後那條測試的
  斷言方向要反過來，`command_dispatch_combination()` 的分類鍵也要多一個維度
  （`give` 修好後會跟 L2 撞同一格）。落在 `scan/`，可與其他修正同 commit。
* **〔command text 缺口 B〕2026-10-14 已處理（`e9b03d2`）：掃描端跳過，不修寫入層。**
  以下是裁定前的發現，保留原文。**這個形狀在 1.21.11 本來就是字面亂碼，
  修寫入層可能是錯的方向。** [遊戲實測 M0-3]（`SPIKE_RESULT.md`
  「M0 遊戲實測」）當初實際下的指令就是 `/data merge block`，`back_text` 的
  `messages` 正是 `['{"translate":"mcmt.test.hello"}', '""', …]`——缺口 B 的形狀，
  也是 `docs/m-command-checklist.md` 4a 的形式 B——結果顯示**字面文字**。1.21.5 起
  指令裡的 component 是 SNBT，字串元素就是字面文字，`data merge` 也不經過
  DataFixer。所以讓 `_decode_command_leaf` 讀得回這個形狀，只會讓 region 指令方塊
  開始寫出 `"{\"translate\":…}"`——遊戲裡從顯示 `{"text":"Hello"}` 變成顯示
  `{"translate":"mcmt.…`，正是 CLAUDE.md 二節「native chunk 裡的舊式 JSON 一律
  跳過」要擋的那件事（`.mcfunction` 沒有解碼守門，**現在就已經**在寫這種 edit）。
  替代方向：掃描端把字串包裝 JSON 的訊息比照舊式 JSON 跳過並計數——**使用者裁定
  沿用 `skipped_legacy_json_in_native_chunk`，不動合約**。pinned 測試改名
  `test_a_json_string_wrapped_merge_message_is_skipped_not_translated`（掃描不產生
  單位＋舊 editplan 的三步鏈 edit 寫入層照舊拒寫）。缺口 B 的原描述：
* **〔command text 缺口 B〕`write/common.py::_decode_command_leaf` 不能還原
  「SNBT 字串包裝 JSON」的 `data merge` 訊息。** 三步鏈 `command→snbt→json_component`
  時它只看最後一步的 codec，直接對含 SNBT 引號的原始 span 跑 `json.loads`——單引號
  解析失敗（`unsupported_encoding`）、雙引號碰巧成功但解出字串而非物件
  （`node_changed`）。底層 splice（Task 7）其實處理得了，是守門這關擋掉。
  **MP2 實測影響**：0（MP2 的 21 個 `data merge block` 訊息全是原生 compound）。
  Task 11 釘在 `test_a_json_string_wrapped_merge_message_is_a_known_write_gap`。
  落在 `write/` 目錄——依 CLAUDE.md §五要獨立 commit 並說明理由。
* **〔command text 缺口 C〕`write/mcfunction_apply.py` 的重放守門 — 2026-09-06
  補上長度那一層，2026-10-14 補上 `raw_snapshot` 那一層（`4be093e`），已完整。**
  現在 `.mcfunction` 與 region／entities 共用 `write/common.py::guard_command_edits`；
  殘餘那條 pinned 測試已反轉成 `test_a_same_length_change_after_extract_is_refused`，
  並補 zip 版與「快照對得上照常寫」的正向測試。以下為原紀錄：

  **先修正一個記錯的描述。** 這條原本寫成「重放永遠成功，把已翻的文字再蓋一次
  同樣的譯文，no-op 但不對稱」。**那個描述只在檔案沒被改過時成立**，而且是因為
  pinned 測試用的 `say Hello world` → `say 你好世界` 剛好冪等（走味的 span
  `[4,15]` 落在 9 字元的字串上仍然解析成「`say ` 之後的全部」）。真實行為是：對
  一行在 extract 之後**被改過**的指令重放，plan 裡的絕對位移會從一個 token 的
  正中央切開，寫出語法壞掉的指令，而報告說 `unwritten: []`——

      plan 抽自：tellraw @a {"text":"Hello"}
      重放到　：tellraw @s {"text":"Hello there, friend","color":"red"}
      結果　　：tellraw @s {"translate":"mcmt.…","fallback":"Hello"}here, friend","color":"red"}

  把已知限制描述成無害，比不知道它存在更糟——這個 repo 的證據文化就建立在這個
  區別上。（唯一擋著它的是 `cli/apply.py` 那個 `world_fingerprint` 閘門，而
  `fingerprint.py::_datapack_files` 確實涵蓋 `datapacks/**`，所以走 `mcmt apply`
  到不了這裡；但 `apply_editplan` 是函式庫進入點，而 `.mcfunction` 是**唯一**只靠
  那一道外層閘門的容器。）

  **2026-09-06 已補**：`_guard_by_length()`（資料夾式與 zip 式兩條路都接）重用
  `write/common.py::_command_length_matches` 本尊做長度比對，長度對不上就拒寫成
  `node_changed`，與 region／entities 同一個判準、同一個理由字串。上面那個示範的
  損壞案例現在被擋下來。

  **殘餘缺口**：`raw_snapshot` 那層逐位元組比對還沒接——使用者把字改成**一樣長**
  的另一句時長度對得上，這一筆照樣寫下去，把使用者剛改的字蓋掉。**沒有一起接的
  理由**：`_decode_command_leaf` 自己還帶著缺口 B，照搬過來會讓 `.mcfunction` 裡
  目前寫得出去的那個形狀反而開始被拒寫——拿一個真缺陷換一個假保護。**缺口 B 修好
  之後才該接上**，屆時
  `test_a_same_length_change_after_extract_is_the_remaining_mcfunction_gap`
  會變紅，那就是提醒。釘在 `tests/unit/test_write_mcfunction_apply.py` 的四條
  （走味 span 被拒／重放被拒／zip 同樣被拒／殘餘缺口）。
* **〔command text 缺口 D〕三個 `skipped_command_*` stats — 已於 2026-09-05 修正。**
  已補上 `extract/emit.py` 與 `cli/extract.py` 中三個計數器的轉接，使其出現在
  `extract.json` 與 CLI 摘要。新增單元測試 `test_the_command_stats_reach_the_extract_document` 涵蓋。
* **〔command text，整支分支 review 抓到、2026-09-06 已修〕兩個不在上面四項裡的
  缺陷。** 兩個都是「舊範圍下碰巧成立的不變式」（CLAUDE.md §五）：

  1. **`.mcfunction` 在複數 `functions/` 目錄下完全隱形，而且沒有任何計數器。**
     1.21 才改成單數 `function/`；1.20 及以前的資料包用複數，遊戲照樣載入。
     [實測] `Arena of Darkness`（1.20.4）四個資料包共 **120 個 `.mcfunction`
     全部**在複數目錄底下，全部被跳過，印出來的摘要跟「這張地圖沒有任何
     function」逐位元組相同。同一個專案在 `sources/datapack.py::_ADVANCEMENT_DIR_NAMES`
     已經對進度目錄解過同一題——該抄的邏輯沒抄過來。已照抄修正。
  2. **`data merge` 的裸字串告示牌訊息被寫成異質 SNBT list，指令再也跑不動。**
     `messages:["Hello","","",""]`（一行字＋三行空，最常見的告示牌形狀）原本走
     translate key，writer splice 進一個 SNBT compound，產出的 `TAG_List` 元素
     型別不一致——`TAG_List` 在格式層帶單一元素型別 id，遊戲的指令解析器吃不下。
     指令方塊寫得進磁碟、指令卻壞了，而報告說 `unwritten: []`。**span 完全正確、
     錯的是型別**：`write/native.py::apply_to_list` 一直守著的 list 同型不變式，
     指令 splice 這條新路徑整個繞過那個 writer。已改走 in_place（重用
     `command_say_text`，不動合約）。同時補上安全網的第二條線
     `assert_command_reparses()`（`tests/conftest.py`）——每一次 splice 之後問一句
     「這還解得回來嗎」，套用在每一格 dispatch 組合與端到端全世界掃描上。
     端到端也補上第六格組合 `("entities_chunk","snbt","literal")`。
* ~~**〔command text 缺口 E〕`_snbt_string_literal` 不跳脫控制字元。**~~
  → **2026-10-14 已修**（`5dfb416`）：兩個修法都用上——SNBT 常值（含 amulet `to_snbt()`
  輸出的原生 compound）寫成跳脫序列，`say`／`me` 含控制字元則拒寫。1.21.11 是否接受
  `\n` 跳脫仍 `[待驗]`。原描述：
  `write/command_span.py::_snbt_string_literal`（約 140 行）只跳脫 `\` 與 `"`。
  譯文裡若有一個裸換行，會原樣 splice 進去：`amulet_nbt.from_snbt` 收得下，但
  1.21.11 的指令解析器收不下，而且在 `.mcfunction` 裡那個換行會把實體行切成兩行、
  之後每一行的行號都平移。**是既有缺陷**——`say`／`me` 的 `innermost == "command"`
  那一格從分支一開始就有這個曝險（`json_component` 那條路安全，因為 `json.dumps`
  先跳脫過）；C2 讓它多涵蓋一個形狀（裸字串 `data merge` 訊息）。兩個修法：在
  `_snbt_string_literal` 裡跳脫控制字元，或在驗證階段直接拒收含 `\n` 的
  command-category 譯文。本波**不修**（不碰 `write/`）。
* ~~**〔CLI 摘要的拒寫原因說明不夠細〕**~~ → **2026-10-14 已修**（`143c688`）：
  採「只改 CLI」的做法，不動合約。`format_apply` 在寫入層拒寫的每個 reason 底下
  列出 detail（相同的合併計數、最多 3 種，其餘指向 `apply_report.json`），新增
  `tests/unit/test_cli_apply_format.py`。原描述：（2026-10-14 遊戲實測時發現）`say` 譯文含
  控制字元被拒寫時，`mcmt apply` 摘要印的是 `unsupported_encoding` 共用的說明
  「這種節點形狀還沒有寫入路徑」，會誤導；正確原因只在 `apply_report.json` 的
  `detail`。不影響安全。修法方向：摘要對 `unsupported_encoding` 同時印出 detail，
  或拆一個新的 reason（後者是合約改動）。
* **〔擴範圍檢查清單，belt-and-braces〕新的寫入路徑有沒有經過那個 writer？**
  擴大寫入範圍時要問一句：這條新路徑有沒有走過強制 list 同型／世代分派／
  `raw_snapshot` 的那個 writer，還是繞過去了？C2 正是繞過去的實例（教訓目前只
  寫在 CLAUDE.md §二的 command-text 註記裡）。`EXPECTED_COMMAND_COMBINATIONS`
  的相等斷言已經機械性地逼問這件事，這條只是備援提醒。

## 開工前該補掉的兩件事

**兩項都已解決**（第 1 項 2026-08-21、第 2 項由 M4）。留著是因為它們的結論仍然重要。

1. ~~**混合 list 存到磁碟後是什麼形狀**~~ → **2026-08-21 解決，而且不用進遊戲**：那種 list **不可能存在**。`TAG_List` 在 NBT 格式層就帶單一元素型別 id，把 `CompoundTag` 塞進 String list 會直接 `TypeError`。所以「四行全部改寫」是**格式強制**的，寫入層連「不小心只改一行」都做不到。詳見 `SPIKE_RESULT.md`。
2. ~~**DV < 4325 的 chunk 經 DataFixer 升級後，舊式 JSON 是否被正確解析**~~ → **M4-2 已答**：三種舊式形式全部被解析，且存回磁碟時轉成 `{"": …}`。4325 這條界線由對照實驗確立。

其餘 `[待驗]` 項見 `SPIKE_RESULT.md`「尚待驗證」表。

---

## 環境備忘

- **語料地圖在版本隔離的資料夾**：`%APPDATA%\.minecraft\versions\1.21.10\saves`，不是 `%APPDATA%\.minecraft\saves`。找不到 Minecraft Party 2 就是找錯地方了。
- `spike/.venv` 與 `spike/.venv_alt` 共 134 MB，已 gitignore。
- `claude-code-stats/` 是**放在同一個資料夾裡的第三方工具**，與 mcmt 無關，已 gitignore。
- 驗證合約：`.venv\Scripts\python tools/validate_contracts.py`（目前 48 passed, 0 failed）。`jsonschema` + `referencing` 是 dev 相依，不是執行期相依。
- 開發環境是根目錄的 `.venv`（`pip install -e ".[dev,lz4]"`），跑測試：`.venv\Scripts\python -m pytest`（2026-10-15 為 902 passed；`pyproject` 的 `addopts = "-q"` 會吃掉摘要行，要看總數加 `-o addopts=""`）。**全域 python 沒有 pytest**，直接打 `python -m pytest` 會失敗。
- 跑 CLI：`.venv\Scripts\python -X utf8 -m mcmt.cli {doctor|sandbox import|extract|apply} …`。
- **heredoc 會吃掉反斜線**：用 `bash << 'PY'` 寫含 `
`、``、` ` 的 Python 原始碼會被破壞（曾寫出 NUL byte 讓檔案無法解析）。含跳脫序列的檔案改用 Write 工具，或用 `chr(92)` 組出反斜線。
- 真實地圖的路徑：MP2 在 `versions.21.10\saves`、`Arena of Darkness` 在 `versions.20.4\saves`、`100 Ways To Die` 在桌面、自建探測世界 `TT_WORLD_NAME_PROBE` 在 `.minecraft\saves`。**`-X utf8` 是必要的**，Windows 終端機的預設編碼會把中文報告印成亂碼。
- `sandbox/` 已有一份 95 MB 的「100 Ways To Die」副本（gitignore）。M4 要的是 DataVersion 3955 的 chunk，那在 Minecraft Party 2；這份是 4325，可以留著當寫入測試的對象。
- 測試 fixture 一律取自自建的 `TT_WORLD_NAME_PROBE`，不放語料地圖的內容（授權考量，見 M3 那節）。
