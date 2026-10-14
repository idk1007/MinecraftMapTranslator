# M-command — 指令文字進遊戲驗證（可重跑程序）

**目的**：把「command text」功能（指令方塊 `Command` ＋ datapack `.mcfunction` 的
白名單動詞解析／外科式寫回，13 個任務、SCHEMA_VERSION 6 → 7）從
`[待驗]` 升級。程式碼／單元／端到端／MP2 全掃已經驗過
（見 `SPIKE_RESULT.md`「指令文字方案 1 MP2 全掃」）；**沒驗過的只有一件事——
遊戲把工具寫回的指令算繪出來的結果對不對**。這件事只能進 1.21.11 用肉眼看。

**狀態：尚未執行。** 執行完把結果寫回 `SPIKE_RESULT.md`（見最後一節），
標 `[遊戲實測]`。這份文件留著可重跑：換 Minecraft 版本、或改動
`write/command_span.py`／`write/common.py` 的指令寫入路徑時，照這套再跑一次。

這一項不寫程式碼（除非第 ④ 點的結果要求改 `_snbt_string_literal`，見該節）。

---

## 為什麼用 `TT_WORLD_NAME_PROBE`

跟 M0 同一個理由：這是本專案自建的 1.21.11 探測世界，DataVersion 全部是 native
（doctor 覆核見 `SPIKE_RESULT.md`），沒有 legacy chunk 的變因，指令方塊寫進去
就是 native 路徑。世界資料夾在 `%APPDATA%\.minecraft\saves\TT_WORLD_NAME_PROBE`；
若已刪除，隨便開一個 1.21.11 創造模式世界、開作弊即可，這個驗證不依賴世界內容。

**為什麼要你手動放指令方塊、手動貼指令**：跟 M8 放告示牌同一個理由——這個工具
從不生成 `/setblock`，那要猜 1.21.11 的方塊實體 NBT 語法，猜錯的症狀是「進遊戲
什麼都沒出現」，白跑一趟。你在遊戲裡打的指令，是**遊戲自己**把 `Command` 欄位
寫成正確形狀，工具再從那個已知good的形狀去 extract／apply。指令方塊的 `Command`
字串沒有「空白對照組」可挑（不像告示牌），所以改用「先看未翻版、再看已翻版」
的前後對照。

---

## 一、進遊戲手動佈置（約五分鐘）

在 `TT_WORLD_NAME_PROBE`，`/gamemode creative`，找一塊平地：

1. **放一塊站立式告示牌**（`oak_sign` 之類，不上蠟），四行留空，按 Esc 離開編輯。
   F3 記下它的座標，設為 `SX SY SZ`。這是第 ② 案 `data merge` 的目標。
2. **放四個脈衝型指令方塊**（`/give @s command_block`），排成一列，每個前面放一個
   按鈕或拉桿。F3 記下四個座標。四個分別貼下面四條指令（把 `SX SY SZ` 換成真的
   數字，`~ ~ ~` 也可以但要站在告示牌上）：

   | # | 指令方塊貼什麼 | 驗的是 |
   |---|---|---|
   | ① `tellraw` | `tellraw @a {"text":"MCMD tellraw source A"}` | L1：整包 JSON 參數 |
   | ② `data merge`（原生 SNBT） | `data merge block SX SY SZ {front_text:{messages:[{text:"MCMD merge line one"},{text:""},{text:""},{text:""}]}}` | L2：指令內含 SNBT，SNBT 內含 component（`command→snbt` 兩步鏈） |
   | ③ `say` | `say MCMD say source C` | in_place：純文字尾巴，動詞前綴不能動 |
   | ④ `data merge`（字串包裝 JSON） | `data merge block SX SY SZ {back_text:{messages:['{"text":"MCMD wrapped line"}','""','""','""']}}` | **2026-10-14 起刻意不抽**（缺口 B 的裁定）：這個形狀在 1.21.11 是字面亂碼（[遊戲實測 M0-3]）。這一格驗的是「extract 跳過它、計入 `skipped_legacy_json_in_native_chunk`，apply 後 `back_text` 原封不動」。見第四節 4c。 |

3. **放一個 datapack `.mcfunction`**（可選，覆蓋 `datapack_mcfunction_file` 容器）：
   在世界的 `datapacks/` 底下建一個最小 datapack，`data/<ns>/function/mcmd_test.mcfunction`
   放兩行：
   ```
   tellraw @a {"text":"MCMD mcfunction line one"}
   say MCMD mcfunction line two
   ```
   `pack.mcmeta` 的 `pack_format` 用 94（`SPIKE_RESULT.md` 標頭記 94.1，`pack.mcmeta`
   填整數主版本，兩者一致，不用停下來懷疑）。進遊戲 `/reload`，之後用
   `/function <ns>:mcmd_test` 觸發。

   > **目錄名用單數 `function/` 或複數 `functions/` 都可以**——工具兩種都認
   > （1.21 起是單數，1.20 及以前是複數）。想順便驗到複數那條路徑就用複數。

4. **先各觸發一次**（按鈕／`/function`），確認未翻版就能正常運作：聊天出現
   `MCMD tellraw source A`、告示牌正面出現 `MCMD merge line one`、聊天出現
   `<你> MCMD say source C`……等等。**這一步是「你佈置對了」的訊號**——之後任何
   變化才確定是工具造成的。存檔離開遊戲。

> 若嫌手動佈置四個指令方塊煩：這批佈置目前沒有 `tools/` 準備腳本
> （不像 M4 的 `m4_prepare.py`）。理由是指令方塊要人進遊戲放、按鈕要人接，
> 腳本頂多省下「不要打錯字」，收益低。未來若這個驗證要常跑，值得補一個
> 「找出世界裡所有 `minecraft:command_block` 方塊實體、把它們的 `Command` 改寫成
> 上表四條」的腳本，架構抄 `tools/m4_prepare.py`（`read_region` → 改 `block_entities`
> → `BackupSet` → `write_region`），但仍需要人先進遊戲放方塊。

---

## 二、跑 extract / apply（在 worktree 內，`.venv`）

```
.venv\Scripts\python -X utf8 -m mcmt.cli sandbox import "%APPDATA%\.minecraft\saves\TT_WORLD_NAME_PROBE" --name mcmd
.venv\Scripts\python -X utf8 -m mcmt.cli doctor "sandbox\mcmd"
.venv\Scripts\python -X utf8 -m mcmt.cli extract "sandbox\mcmd" --lang zh_tw
```

`extract` 的摘要裡應該看到 `command_say_text` 與 `command_component_text` 兩個
新分類各有數字（① tellraw 與 ④ 的 wrapped 是 `command_component_text`，
② merge 是 `command_component_text`，③ say 是 `command_say_text`）。若某一格
沒被抽到，先停下來查掃描端，不要進遊戲。

編輯 `sandbox\.mcmt-out\mcmd\translations.zh_tw.json`，把這幾筆的 `target` 填上
可分辨的中文（`source` 會告訴你哪筆是哪筆）：

| source 大致長相 | 建議 target |
|---|---|
| `MCMD tellraw source A` | `聊天翻譯成功` |
| `MCMD merge line one` | `告示牌翻譯成功` |
| `MCMD say source C` | `說話翻譯成功` |
| `MCMD mcfunction line one` | `函式聊天翻譯成功` |
| `MCMD mcfunction line two` | `函式說話翻譯成功` |

```
.venv\Scripts\python -X utf8 -m mcmt.cli apply "sandbox\mcmd" --translations "sandbox\.mcmt-out\mcmd\translations.zh_tw.json" --dry-run
.venv\Scripts\python -X utf8 -m mcmt.cli apply "sandbox\mcmd" --translations "sandbox\.mcmt-out\mcmd\translations.zh_tw.json"
```

**看 apply 摘要的 `unwritten` / refuse 欄**：① ② ③ 與 `.mcfunction` 兩筆應該
全部寫入、0 拒寫。**④ 的 wrapped 根本不會出現在待翻檔裡**（2026-10-14 起掃描端
跳過，extract 摘要的「新世代 chunk 裡的舊式 JSON」計數會包含它的四行），所以
`translations.zh_tw.json` 裡找不到 `MCMD wrapped line`——那是預期行為，不是
佈置弄錯（端到端測試 `test_a_json_string_wrapped_merge_message_is_skipped_not_translated`）。

`apply` 會在 `sandbox\mcmd\` 產生 `resources.zip`（含 `mcmt.*` 的 zh_tw lang 檔）。

---

## 三、進遊戲看結果

1. 把 `sandbox\mcmd` **整個資料夾複製**到 `%APPDATA%\.minecraft\saves\`
   （工具永不自動複製回去——CLAUDE.md §1.1）。
2. 用 **1.21.11** 開啟，語言切**繁體中文**，`/gamemode creative`。
3. 資源包清單確認 `mcmd/resources.zip` 有生效（沒生效的話 `mcmt.*` key 會顯示
   成字面 key，那是資源包的病不是寫入的病，見失敗分診）。
4. 重新觸發四個指令方塊與 `/function <ns>:mcmd_test`，逐項核對：

### 要回報的四件事（照抄 spec §9.3）

| # | 檢查 | PASS | FAIL |
|---|---|---|---|
| ① `tellraw` 的 `{"translate":key}` | 聊天出現 **`聊天翻譯成功`**（資源包解出的譯文） | 聊天出現字面的 `{"translate":"mcmt.…"}` 或字面 key，或指令報紅字錯誤 |
| ② `data merge` 寫的告示牌 | 告示牌正面第一行出現 **`告示牌翻譯成功`** | 出現字面 SNBT／字面 key，或 `data merge` 執行報錯 |
| ③ `say` 的 in_place 替換 | 聊天出現 **`<你> 說話翻譯成功`**——**動詞前綴（`<你> ` 那段）完整、只有尾巴被換掉** | 前綴不見了、或整行變成 `say 說話翻譯成功` 字面顯示、或原文沒被換掉 |
| ④ SNBT 字串常值的跳脫方式 | 見第四節（4a 問解析器、4c 確認跳過、4d 裸字串、4e 控制字元） | 見第四節 |

`.mcfunction` 兩行（`函式聊天翻譯成功` / `<你> 函式說話翻譯成功`）跟 ① ③ 同標準，
順便確認 datapack 容器這一側寫入也 OK。

**截圖每一項**，聊天內容從 `%APPDATA%\.minecraft\logs\latest.log` 抓原文，
不要對著聊天視窗抄（抄會抹平引號與跳脫，而這次 ④ 要驗的正是引號與跳脫）。

---

## 四、第 ④ 點：SNBT 字串常值的跳脫方式（spec §4／§9.3 的 `[待驗]`）

**背景**：`write/command_span.py::_snbt_string_literal` 目前把三步鏈
（`command→snbt→json_component`）組出來的 JSON 包成一個**雙引號＋反斜線跳脫**的
SNBT 字串常值：`"{\"translate\":\"mcmt.test.cmd_merge\"}"`。設計文件標
`[待驗]`：Mojang 自己的序列化器可能傾向用**單引號、不跳脫**
（`'{"translate":"mcmt.test.cmd_merge"}'`）。要驗的是：**1.21.11 的指令解析器
接不接受雙引號＋跳脫這個形式，還是會報錯／把 `\"` 當字面字元顯示。**

**問題**：走完整 mcmt 管線驗不到——第 ④ 格的 wrapped 訊息 2026-10-14 起在
掃描端就被跳過（缺口 B 的裁定），那段文字根本不會被寫進存檔。但
`_snbt_string_literal` 仍然被 4d 的裸字串 `data merge` 與缺口 E 的控制字元跳脫
用到，所以「雙引號＋反斜線被不被接受」仍然要問，用底下的手打指令直接問遊戲的
解析器。

> **預期**：形式 A／B 都會把 `{"translate":…}` 顯示成**字面文字**，不是
> `跳脫驗證成功`——形式 B 就是 [遊戲實測 M0-3] 當初下的那條指令。這一節真正要看
> 的是**形式 A 有沒有紅字**：沒有紅字、而且顯示的字面文字裡沒有多出來的反斜線，
> 就代表雙引號＋反斜線這個跳脫形式被解析器正確解開了。

### 4a. 手打指令，問解析器（現在就能做，不依賴任何缺口）

前提：世界裡有那份 `resources.zip`（第三節已複製），它含
`mcmt.test.cmd_merge` → 某個可分辨中文。若沒有，照 `tools/make_m0_pack.py`
的做法手搓一個最小 pack，key 用 `mcmt.test.cmd_merge`、value 用 `跳脫驗證成功`。

站在告示牌 `SX SY SZ` 上，在聊天列**逐字**打這兩條，各按一次 Enter：

```
# 形式 A —— _snbt_string_literal 現在產生的形式（雙引號＋反斜線）
data merge block SX SY SZ {front_text:{messages:["{\"translate\":\"mcmt.test.cmd_merge\"}","\"\"","\"\"","\"\""]}}

# 形式 B —— 備援方案（單引號，內部不跳脫）
data merge block SX SY SZ {back_text:{messages:['{"translate":"mcmt.test.cmd_merge"}','""','""','""']}}
```

> **形式 B 會蓋掉 `back_text`**，而第一節第 ④ 格的指令方塊寫的也是 `back_text`。
> 照本文件的順序跑，4c 讀到的會是你剛剛手打的結果，不是管線寫出來的結果——所以
> 4c 開頭要先按一次 ④ 的按鈕把 `back_text` 重設回去（下面 4c 第一步已寫明）。
> 想避開這件事的話，把形式 B 打在**第二個告示牌**上。

觀察並回報：

| 觀察 | 代表 |
|---|---|
| 形式 A 被接受（無紅字），告示牌正面顯示字面的 `{"translate":"mcmt.test.cmd_merge"}`（**沒有反斜線**） | **雙引號＋跳脫成立**：解析器把 `\"` 解回 `"`。`_snbt_string_literal` 不用改。`[待驗]` → `[遊戲實測]` |
| 形式 A 報紅字，或顯示的字面文字裡**帶著反斜線**（`{\"translate\"…`） | **雙引號＋跳脫不成立。** 走下面的補救 |
| 形式 A 或 B 顯示 `跳脫驗證成功`（被解析成 component） | **推翻 [遊戲實測 M0-3] 在指令上的延伸**——缺口 B 的裁定（掃描端跳過）前提不成立，停下來回報 |
| 形式 B 被接受（無紅字） | 單引號形式是安全的備援（不論 A 結果如何，記下來） |

### 4b. 補救（只有 4a 的形式 A 失敗時才做）

改 `src/mcmt/write/command_span.py::_snbt_string_literal`：改用**單引號分隔、
內部不跳脫**（單引號字串裡的 `"` 不需要處理，只需處理字串內容自己出現的 `'`）：

```python
def _snbt_string_literal(text: str) -> str:
    """把 text 包成一個 SNBT 單引號字串常值。單引號內 " 不需跳脫，
    只跳脫字串內容自己的 '。[遊戲實測 M-command]：雙引號＋反斜線形式被
    1.21.11 指令解析器拒絕／顯示成字面跳脫字元，故改用此形式。"""
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"
```

這是 `write/` 底下的檔案，照 CLAUDE.md §五**獨立 commit**，訊息寫明理由是
M-command 遊戲實測推翻了雙引號方案。改完，下面這些綁著雙引號＋反斜線預期形式的
測試會變紅，**照新形式改斷言，不是把測試放寬**：
- `tests/unit/test_command_span.py::test_a_string_wrapped_json_leaf_is_re_escaped_correctly`
  ——splice 的位移替換單元測試。
- `tests/unit/test_command_span.py::test_a_bare_string_merge_message_escapes_quotes_and_backslashes`
  與 `::test_a_bare_string_merge_message_stays_a_string_and_the_command_reparses`
  ——C2（`48240ea`／`d0a09ce`）加的兩條裸字串 `data merge` 跳脫測試。
- `tests/conftest.py::assert_command_reparses`——修正波加的重新解析輔助函式；
  它按動詞挑解析器，改跳脫形式後要確認 `data merge` 那條回讀仍然通過。

另外：
- 同步更新 `docs/superpowers/specs/2026-09-05-command-text-design.md` §4／§9.3
  的 `[待驗]` 註記為 `[遊戲實測]` 並記錄結論。
- `_snbt_string_literal` 的 docstring 把 `[待驗]` 換成 `[遊戲實測 M-command]`。

### 4c. 字串包裝 JSON 被跳過、原封不動（2026-10-14 起的意義）

原本這一格是「缺口 #2 修好之後的完整管線覆核」。缺口 B 的裁定改成掃描端跳過，
所以這裡驗的變成**跳過這個決定本身對不對**：

> **第一步：先按一次 ④ 的按鈕，把 `back_text` 重設成管線的輸入。** 4a 的形式 B
> 剛剛手打覆寫過 `back_text`，不重設的話這一步讀到的是那個手打結果。

1. **跳過的前提成立嗎？** 重設之後看告示牌背面：第一行應該顯示**字面的**
   `{"text":"MCMD wrapped line"}`（不是 `MCMD wrapped line`），二到四行顯示字面
   的兩個引號 `""`。**如果反而顯示成 `MCMD wrapped line` 與空白**，代表 1.21.11
   對指令裡的字串包裝 JSON 會解析，裁定的前提被推翻——停下來回報，這個形狀
   應該重新納入翻譯。
2. **工具沒有碰它嗎？** 跑過第二節的 apply 之後，④ 的指令方塊 `Command` 應該
   跟佈置時一字不差（`/data get block <④ 的座標> Command`，從 `latest.log` 抓）。

### 4d. 裸字串 `data merge` 訊息（現在就能端到端驗，不等任何缺口）

形式 A／B 都是**字串包裝 JSON**（缺口 #2 的形狀），管線目前拒寫，所以 4a–4c
全都繞過管線在問解析器。但 C2（`d0a09ce`／`48240ea`）之後多了一條**現在就會
在真實地圖上寫出去**的路徑：`messages[]` 的元素是一句**解不出 JSON 的裸文字**時
（`messages:["中文","","",""]`——一行字＋三行空，最常見的告示牌形狀），這筆改走
`command_say_text` → in_place，writer 用 `_snbt_string_literal` 把譯文包成一個
SNBT 字串常值 splice 回去，list 維持全字串。**這條路徑前面沒有缺口**，extract →
編輯 → apply 一路走得通。

步驟：

- 在一個指令方塊放
  `data merge block SX SY SZ {front_text:{messages:["中文","","",""]}}`
  （`中文` 換成任何解不出 JSON 的純文字，例如 `merge 裸字串來源`）。
- 跑 extract／apply（第二節那套），把這筆的 `target` 填成可分辨的譯文
  （例如 `裸字串翻譯成功`）。apply 摘要裡這筆**應該寫入、0 拒寫**——它不是
  缺口 #2 的形狀，不會進 `unwritten`。
- 進遊戲觸發那個指令方塊，確認：
  - 告示牌正面第一行顯示 `裸字串翻譯成功`（直接是譯文，不是 `{translate:…}`）；
  - `/data get block SX SY SZ front_text` 從 `latest.log` 讀回的是**合法 SNBT**
    ——沒有紅字錯誤、沒有字面反斜線、`messages` 仍是四個字串。

**這一格是 live 的，不是 deferred**：不像形式 A，它不需要 4c 的「缺口 #2 修好後」
前提。PASS 就直接標 `[遊戲實測]` 寫回 `SPIKE_RESULT.md`。

### 4e. 控制字元跳脫（缺口 E，2026-10-14）

`_snbt_string_literal` 現在把譯文裡的換行寫成 `\n` 跳脫（`[文件]`：1.21.5 起
SNBT 支援 `\n`／`\t`／`\uXXXX`）。在 4d 那個裸字串 `data merge` 指令方塊的待翻檔
裡，把 `target` 改成含換行的譯文（JSON 裡寫 `"第一段\n第二段"`），apply 之後：

- 指令方塊 `Command` 應該是單行，含字面的 `\n` 兩個字元（從 `latest.log` 抓）；
- 觸發後**沒有紅字**；告示牌那一行的顯示（換行被算繪成什麼、或被截掉）照實
  記下來——告示牌的一行本來就放不下換行，這裡要確認的只是「指令解析得了」。
- 反向：把 `say` 那筆的 `target` 也填含換行的譯文，apply 摘要應該列為
  `unsupported_encoding`、detail 寫「控制字元」，指令方塊原封不動。

---

## 五、失敗分診

譯文沒出現時，**不要一次改兩個變因**，按這個順序排除：

1. 語言真的切到 `zh_tw` 了嗎（不是 `zh_cn`）？
2. `sandbox\mcmd\resources.zip` 在世界資源包清單裡有出現且在**已啟用**那側嗎？
   （出現但沒生效 vs 根本沒出現，是兩種不同的病。）
3. zip 內根目錄直接是 `assets/` 與 `pack.mcmeta`，**沒有外層包裹資料夾**嗎？
   （`python -m zipfile -l sandbox\mcmd\resources.zip`）
4. `assets\mcmt\lang\zh_tw.json` 是 UTF-8 **無 BOM** 嗎？
5. **控制組**：把某一格指令方塊的參數改成原版 key
   `{"translate":"block.minecraft.diamond_block"}`。它已是 `[遊戲實測]` 有效。
   - 控制組**有效**、自訂 key 無效 → 問題在資源包（1–4）。
   - 控制組**也無效** → 問題在指令的寫入形狀，不在資源包。
6. ③ `say` 前綴不見了 → 看 `apply` 是不是把它當 `translate_key` 而不是
   `in_place`（`command_say_text` 必須走 in_place，`strategy.py` 的對照）。
7. ① 指令報紅字（指令根本沒執行）→ 從 `sandbox\mcmd` 用工具重讀那個
   `Command` 字串貼出來看，八成是 splice 把括號／引號切壞了——那是
   span 定位器或 `_compose_replacement` 的 bug，記進 `docs/journal/`。

---

## 六、收尾：把結果寫回

**單人開發沒有第二個人會提醒你這一步。** 進完遊戲後：

1. **`SPIKE_RESULT.md`**：新增一節「指令文字 M-command 遊戲實測（<日期>）」，
   四項（① tellraw／② data merge／③ say／④ SNBT 跳脫）各記顯示結果與證據等級。
   PASS 標 `[遊戲實測]`；有偏差就記實際現象並說明對策。同時更新
   「尚待驗證」表——把對應列劃掉並註明本節。
2. **④ 若形式 A 失敗**：照第 4b 節改 `src/mcmt/write/command_span.py`
   （獨立 commit）、`docs/superpowers/specs/2026-09-05-command-text-design.md`
   §4／§9.3 的 `[待驗]`、對應單元測試。
3. **`docs/STATUS.md`**：把「指令文字進遊戲驗證 `[待驗]`，程序見
   `docs/m-command-checklist.md`」這行改成已完成，或記下未過的項目。
4. 若推翻了先前的推論，**保留原推論並說明為何被推翻**，不要直接改掉
   （這份專案的證據分級與自承錯誤是它的價值所在）。
