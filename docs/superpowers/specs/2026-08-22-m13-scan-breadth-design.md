# M13 掃描廣度 — 設計

**日期**：2026-08-22 · **前置**：M12 完成

> **狀態：M13.0–M13.4 已完成並合併**（計畫 `docs/superpowers/plans/2026-08-22-m13a-items-and-entities.md`，
> 18 個 commit，`62ec1e2..015cb47`）。**M13.5–M13.9 待實作**，那就是 M13b。
>
> 實作過程中有兩處與本文件不同，以實作為準：
>
> 1. **第 8 節說 M13.4 需要「寫入層 entities 路徑（`write/` 獨立 commit）」——實際上不需要。**
>    `entities/*.mca` 就是 region 格式，`_apply_to_region` 用 `container["path"]` 去
>    `world / relative` 讀寫，現有的外科式路徑直接可用。改成用一條測試證明它。
> 2. **第 4 節的 `kind → writer` 顯式分派還沒建立。** M13a 只把 `apply.py` 的
>    **值**分派改成看 `value.kind`（原本看 `node_path` 形狀，那個等價關係在範圍擴大後
>    失效，害草稿書頁被寫成 JSON 字串）。**容器種類的分派是 M13b 的 M13.5 一定要做的第一件事**
>    ——`level_dat` 進來的那一刻就需要它，而三種寫入器的保證等級不同。

v1 目前只掃兩種東西：告示牌與方塊實體的 `CustomName`。M13 把掃描範圍擴大到
**所有不需要指令語法解析的來源**。

指令方塊的 `Command` 與 datapack 的 `.mcfunction` **明確不在範圍內**——那不是新決定，
架構計畫的「不做」清單早就寫了「需要指令語法解析，工作量最難估」，`tree/codecs/command.py`
也是明確拋 `NotImplementedError` 的。

---

## 1. 這個範圍是怎麼決定的

不是照清單推的，是**清點出來的**。用一個唯讀腳本走遍三張真實地圖的每一個字串節點、
過一次 denylist、把沒被擋下來的按正規化路徑分組。相異數才是譯者真的要打的量。

| 來源 | Arena of Darkness | 100 Ways To Die | Minecraft Party 2 |
|---|---|---|---|
| 告示牌（已支援） | 2,992 / **580** | 5,700 / **937** | 47,000 / **455** |
| 方塊實體 `CustomName`（已支援） | 9,582 / **24** | 70 / **4** | 2,208 / **82** |
| 物品名 + lore（含容器遞迴） | 3,710 / **147** | 28 / **20** | 有，含深度巢狀 |
| 書本 | 180 / **60** | 438 / **176** | 大量，深度巢狀 |
| 實體 `CustomName` | 333 / **56** | 17 / **12** | 有 |
| `text_display` 的 `text` | 66 / **43** | 184 / **169** | 有（含 `with` 參數） |
| `CustomBossEvents[].Name` | 27 / **27** | 3 / **3** | — |
| 記分板 `Objectives[].DisplayName` | 168 / **168** | 156 / **156** | — |
| 記分板 `Teams[].DisplayName` | 17 / **17** | 13 / **13** | — |
| datapack advancement | — / **56** | — / **0** | — / **84** |
| ~~指令方塊 `Command`~~ | ~~9,491 / 6,699~~ | ~~3,978 / 2,771~~ | ~~1,500 / 396~~ |
| ~~datapack `.mcfunction`~~ | ~~120 檔~~ | ~~1,557 檔~~ | ~~2,613 檔~~ |

### 清點逼出來的三個發現

**① 物品有新舊兩套格式，而且真實語料各佔一套。**
`Arena of Darkness`（1.20.4，DV 3700）是 `Items[].tag.display.Name`，值是 JSON 字串；
`100 Ways To Die`（1.21.5）是 `Items[].components."minecraft:written_book_content"`。
**分水嶺是 DV 3837（1.20.5），和 chunk 結構的 4325 不是同一條線。** 掃物品實際上是掃
兩套形狀。三層巢狀也確認存在（AoD 的 `Items[] → BlockEntityTag/Items[] → tag/display/Name`，
7 個）。

**② `Lock` 是新的危險路徑，而且是最兇的那種。**
AoD 有 107 個 `block_entities[].Lock`（值 `"Locked"`）。那是容器鎖，**值必須與鑰匙物品
的名字完全相同**才能開箱——翻了它，箱子永遠打不開，而症狀離原因很遠。
`SPIKE_RESULT.md` 的排除清單裡沒有它。

**③ `Minecraft Party 2` 已經完全在地化了。**
它的節點大量是 `{translate: "mcp.X", fallback: "..."}`：告示牌 750 個相異 key、書頁 26、
物品 28、advancement 84，連實體武器的名字都是；`resources.zip` 裡有 5 個語言檔、
50,959 個 key（含 `zh_cn`）。照現行邏輯處理會把 `mcp.SignStartSlot` 換成我們的 key，
**讓一張支援 5 種語言的地圖退化成只支援一種**。

---

## 2. 架構決定

### 掃描層做註冊表，寫入層顯式分派

考慮過三種：兩邊都做註冊表、兩邊都用 if/elif、混合。採用**混合**，理由是這兩層的
性質真的不同：

* **掃描來源之間是同型的**——每一個都只做「找到文字節點、記下它在哪」，讀出來之後
  交給同一套嗅探／攤平／規則引擎。抽象沒有藏起任何東西。
* **寫入器之間不同型**——保證等級不一樣（外科式 vs 整份重編 vs 檔案重寫），失敗的
  後果也不一樣。這個不對稱**必須看得見**，一個共同介面會讓它們看起來一樣安全。
  這正是 CLAUDE.md 對 `write/legacy.py` 與 `write/native.py` 那條禁令在講的事。

### 物品是跨來源的共用元件

`scan/sources/item.py` 收一個物品 compound、yield 裡面所有文字節點、**自己遞迴進容器**。
被三個來源呼叫：方塊實體的 `Items[]`、實體的 `ArmorItems[]`/`equipment`/`item`/`weapon`、
`level.dat` 的 `Player.Inventory[]`。三邊各寫一份遞迴是最該避免的事——三層巢狀是實測
存在的，而漏掉一層的症狀是「有些物品名沒被抽出來」，沒有例外也沒有紅字。

### 新舊兩套格式放同一個模組

由物品自己有 `components` 還是 `tag` 決定，**不看 DataVersion**（CLAUDE.md 二節）。

| | 新（1.20.5+） | 舊 |
|---|---|---|
| 物品名 | `components."minecraft:custom_name"` / `item_name` | `tag.display.Name` |
| lore | `components."minecraft:lore"[]` | `tag.display.Lore[]` |
| 成書 | `components."minecraft:written_book_content"`（`title.raw` / `author` / `pages[].raw`） | `tag.title` / `tag.author` / `tag.pages[]` |
| 草稿書 | `components."minecraft:writable_book_content".pages[].raw` | `tag.pages[]` |
| 容器 | `components."minecraft:container"[].item` | `tag.BlockEntityTag.Items[]` |
| 收納袋 | `components."minecraft:bundle_contents"[]` | `tag.Items[]` |
| 弩上的箭 | `components."minecraft:charged_projectiles"[]` | `tag.ChargedProjectiles[]` |

這與 `write/legacy.py` vs `write/native.py` 的不對稱**不同類**，所以不拆成兩個模組：
那邊是「寫出去的形狀不同」，這邊只是「讀進來的路徑不同」，讀完之後都是同一種
component，交給同一套嗅探與攤平。寫回去靠 `node_path` 走回原位，寫入層不需要知道
它來自哪一套。

> **舊格式的一個坑**：成書與草稿書**共用** `tag.pages[]`，差別在物品 id
> （`written_book` vs `writable_book`）與值的形狀（JSON 字串 vs 純字串）。
> 只看路徑會把草稿書當成書處理，而草稿書頁是無包裝的 `TAG_String`，只能 `in_place`。

**`item.py` 是嚴格白名單**：只抽上表列出的那些欄位，**其餘一律忽略、也不遞迴進去**。
不是「走遍物品的樹再靠 denylist 擋」——那個方向錯了，因為物品底下的機制標籤多到
列不完（`Enchantments`、`AttributeModifiers`、`Trim`、`Potion`、`CanPlaceOn`、
`BlockStateTag`、`SkullOwner`、`custom_data`…），而漏擋一個的後果是翻掉識別碼。

白名單的代價是「新版本加了新的文字組件我們不會自動抽到」。那個代價是對的方向：
**漏抽看得見**（節點數對不上清點），**誤翻看不見**（地圖壞掉時已經來不及）。
denylist 在這裡只是第二道防線，不是主要機制。

### `node_path` 不需要 `decode` 步驟

舊格式的物品名 `Items[].tag.display.Name` 的值整個就是一個 JSON component，
嗅探成 `json_string_object`，寫入時整個節點替換。`decode` 步驟（帶 `span` 位移）是給
「一個字串裡有多處要翻譯」用的，那是指令解析才需要——不在這個範圍內。

---

## 3. 掃描層

```
scan/registry.py            來源協定與清單
scan/sources/region.py      現有，擴充：block_entities[].Items[] · Book
scan/sources/entities.py    新：entities/*.mca 的 Entities[] 與 Passengers[]
scan/sources/item.py        新：跨來源共用，兩套格式 + 遞迴
scan/sources/level_dat.py   新：LevelName · CustomBossEvents[].Name · Player.Inventory[]
scan/sources/scoreboard.py  新：Objectives[]/Teams[] 的 DisplayName 與前後綴
scan/sources/datapack.py    新：advancement JSON 的 display.title/description
```

每個來源回報 `(TextNode, container)`。`extract/build.py` 不再自己走 region 檔，改成
跑過註冊表裡的每一個來源——它現在硬編碼的那段就是新增來源時必須改的地方，而 M13
之後還有 v2 的指令解析要進來。

**category 對照**（全部已在合約的 enum 裡）：

| 來源路徑 | category | strategy |
|---|---|---|
| 物品的 `custom_name` 組件 | `custom_name` | translate_key |
| `item_name` | `item_name` | translate_key |
| `lore[]` | `lore` | translate_key |
| 成書 `title.raw` | `book_title` | **in_place**（[遊戲實測] 只吃字串） |
| 成書 `author` | `book_author` | **in_place** |
| 成書 `pages[].raw` | `book_page` | translate_key |
| 草稿書 `pages[].raw` | `draft_book_page` | **in_place** |
| 實體 `CustomName` | `entity_name` | translate_key |
| `text_display` 的 `text` | `text_display` | translate_key |
| `CustomBossEvents[].Name` | `bossbar` | translate_key |
| `Objectives[].DisplayName` | `objective` | translate_key |
| `Teams[].DisplayName` | `team` | translate_key |
| `Teams[].MemberName{Prefix,Suffix}` | `team_affix` | translate_key |
| `LevelName` | `level_name` | **in_place** |
| advancement `display.title` | `advancement_title` | translate_key |
| advancement `display.description` | `advancement_description` | translate_key |

> **`custom_name` 與 `block_entity_name` 是兩個不同的 category，很容易混。**
> 前者是**物品**的 `minecraft:custom_name` 組件（走 translate key），後者是**方塊實體**
> 的 `CustomName` 欄位（[遊戲實測 M11-3] 只吃字面文字，走 `in_place`）。
> 名字像、行為相反。

`level_name` / `book_title` / `book_author` / `draft_book_page` 早就在
`model/strategy.py` 的 `IN_PLACE_CATEGORIES` 裡，而 `in_place` 的 `plain_string` 形狀也
已經實作並有單元測試——**只是到目前為止沒有任何掃描路徑走得到它**。M13 是它第一次
真的被用到。

---

## 4. 寫入層

`write/apply.py` 換成顯式的 `kind → writer` 對照。**每個寫入器一個檔案，各自在檔頭
寫明它的保證到哪裡。**

| kind | 寫入器 | 保證 |
|---|---|---|
| `region_chunk` / `entities_chunk` | 現有的 region 路徑 | **外科式**：未改動的 chunk 原封複製原始壓縮位元組 |
| `level_dat` / `scoreboard_dat` | `write/datfile_apply.py`（新） | **只到 L1**：整份解析→序列化，位元組一致已在真實 `level.dat` 上實測。這裡沒有外科式寫入這回事（M3.2） |
| `datapack_file` | `write/datapack_apply.py`（新） | **檔案重寫**。zip 沿用 `pack.py` 的做法整份重建、既有條目原樣搬運 |

**`entities_chunk` 不是新的寫入器**——`entities/*.mca` 就是 region 格式，`write_region`
直接能用，外科式保證原封不動。它只是 `by_file` 分組時多一條路徑來源。

**`datapack_file` 是工具第一次改動地圖自己的檔案**（不是它的存檔資料）。M4-5 的教訓
是這類事要在報告裡講清楚，所以會有一條 `warnings` 明確列出動了哪些 datapack 檔。

備份：`BackupSet.protect` 對 `level.dat` 與 datapack zip 一樣適用，順序不變
（備份 → 改 → 寫）。

### 共用寫入器不得寫死根節點

`level.dat` 的根是 **`Data`**（大寫），`scoreboard.dat` 的根是 **`data`**（小寫）。
清點輸出直接證實了這件事：`Data/CustomBossEvents/…` 對 `data/Objectives/…`。

**`write/datfile_apply.py` 完全不碰根鍵名**——它只照 `node_path` 一步一步走，而
`node_path` 本來就從根開始（合約 sample 裡 `level_name` 的路徑就是
`[key(Data), key(LevelName)]`）。這不是要小心的事，是設計上就不該知道的事。

知道根鍵名的是**掃描來源**，而且各自**動態解析**：先看 compound 裡實際有哪個鍵，
不是寫死一個字串。兩個理由——版本之間改過大小寫這種事已經發生過一次（就是這兩個
檔案本身），而寫死的症狀是「這個檔案掃出 0 個節點」，看起來和「這個檔案本來就沒有
可翻譯的東西」一模一樣。

### `datfile_apply` 的寫入必須是「暫存 → 驗證 → 原子替換」

`nbtio/datfile.py` 的 `write_dat` 目前是「寫 `.mcmt-tmp` → `os.replace`」，
**中間沒有驗證**。region 那邊不需要這一步（外科式寫入把未改動的位元組原封送回，
壞掉的只可能是我們自己編的那一個 chunk），但 `.dat` 是整份重編的——編壞了就是整個
`level.dat` 沒了，而那是世界的中樞。

所以 `write_dat` 要加一步：**寫完暫存檔之後回讀、重新解析、確認根節點還在**，
通過才 `os.replace`。驗證失敗就刪掉暫存檔並拋錯，原檔一個位元都沒動過。

放在 `write_dat` 而不是 `datfile_apply`，因為那是「把 NBT 安全地寫到磁碟」這件事
本身的一部分，任何呼叫端都該拿到它。`nbtio/` 不在高風險目錄清單裡，但它是位元組層，
所以仍然獨立 commit、獨立測試（含一條「編碼器吐出壞位元組時原檔不變」的測試）。

### 世界指紋要一起改

`nbtio/region.py` 的 docstring 早就預告了這件事。指紋目前只涵蓋 `region/` 的 chunk；
掃 `entities/` 之後，「使用者玩過一次、動了盔甲座」不會讓指紋改變，於是
`extract_fingerprint` 會說「世界沒變」而實際上變了。

**決定：把 `entities/` 納入指紋定義。** 代價是所有既有的 extract 立刻失效，但那會走
`_check_binding` 的明確錯誤訊息（「請重新產生」），不會安靜地對錯節點；per-node 的
`expected_encoding` 守門仍是最後一道關。

---

## 5. 跳過規則

除了既有的三條（denylist 命中、native chunk 裡的舊式 JSON、JSON 解析失敗），新增：

**已在地化的節點**：攤平後的樹裡**任何一處**有 `translate` → 整個節點跳過，計入
`stats.skipped_already_localised`。

用「任何一處」而不是「根節點是」，因為半文字半 key 的樹
（`{"text":"Hello ","extra":[{"translate":"mcp.X"}]}`）重建時一樣會覆蓋掉那個 key。

MP2 的 2,283 個告示牌節點會整面跳過，而它同一批的 2,402 個純文字節點（205 相異）
照抽——這正是想要的。對 `Arena of Darkness` 與 `100 Ways To Die` 幾乎沒有影響
（它們沒有自己的在地化系統）。

> **考慮過但沒採用**：抽出來並在 `note` 警告，讓譯者自己判斷（那是「不做術語表」
> 那個決定的作風）。沒採用是因為這一類和人名不同——**翻了會弄壞別人已經做好的
> 多語言支援**，那是實質損害不只是難看，而且 MP2 會多出 750+ 條雜訊。
>
> 代價要講清楚：**若地圖的 lang 檔沒有你要的語言，那些節點就永遠翻不了。**
> 正確的解法是翻它的 lang 檔，那是另一個里程碑的工作量，而且會把 `%1$s` 格式參數
> 那個問題一起拉進來（[實測] MP2 的 lang 值 37% 含格式參數）。

### 一個已知的代價：記分板的 `DisplayName` 幾乎都是內部名

兩張地圖各 168 / 156 個，**全部相異**，樣本是 `as_lock_uuid4`、`ReFightTime`、
`CustomBossTemplate`。翻它們對玩家沒有意義——只有顯示在側邊欄的那一個看得到——
但工具沒有辦法分辨「這個 DisplayName 是給人看的」還是「作者懶得取名直接沿用 ID」。

**照既定的「工具不介入」原則照樣抽出來**，代價是待翻檔多 324 條雜訊。譯者看得到
原文，`status: skip` 是他的判斷。這裡記下來是因為它是可預期的抱怨來源，不是 bug。

---

## 6. denylist 補強

**掃描層是白名單**（只去找已知的可翻譯欄位，不是走遍樹），所以 denylist 是第二道
防線，重點在「白名單內部會碰到的陷阱」——主要是 `item.py` 遞迴路上的東西：

```
SkullOwner/Name · SkullOwner/Properties/textures[]/Value · .../Signature
BlockStateTag/*  ·  Potion  ·  Trim/material  ·  Trim/pattern
CanDestroy[]  ·  CanPlaceOn[]  ·  minecraft:profile 底下的一切
LootTable  ·  LootTableSeed
Lock  ·  minecraft:lock          ← 新發現，見下
```

外加三項修正：

1. **`Lock` / `minecraft:lock`**——清點新發現。值必須與鑰匙物品名完全相同，翻了箱子
   永遠打不開。要一併寫回 `SPIKE_RESULT.md` 的排除清單。
2. **`LastOutput` 的尾巴 bug**——它寫在 `_DENIED_TAILS`（路徑尾巴），只擋結尾正好是
   `LastOutput` 的節點；`LastOutput/text`、`LastOutput/extra[]/translate` 全漏，
   `100 Ways To Die` 就漏了 6,000 多個，而且它們含原版 translate key。
   改放 `_DENIED_ANYWHERE`。
3. **`profile/properties/value` 認不到 `minecraft:profile`**——規則寫的是 `profile`，
   1.20.5+ 的真實鍵名帶命名空間。

M6 的回歸測試（走過每一個字串節點問規則引擎）會涵蓋這三項。

---

## 7. 合約

**不需要改，也不需要 bump `SCHEMA_VERSION`。** 逐項對過：

* `container.kind` 的 `entities_chunk` / `level_dat` / `scoreboard_dat` / `datapack_file` 全在
* `category` 的 `item_name` / `custom_name` / `lore` / `book_*` / `draft_book_page` /
  `entity_name` / `text_display` / `bossbar` / `objective` / `team` / `team_affix` /
  `advancement_*` 全在
* `stats` 是 `additionalProperties: true`，新的計數欄位不必改 schema
* `occurrence.excluded.reason` 不需要新值

世界指紋改變不是合約改變——它讓既有 extract 失效，但走 `_check_binding` 的明確錯誤。

---

## 8. 任務切分

順序按「先前置、再重構、再由不需要新寫入器到需要」。

| # | 任務 | 備註 |
|---|---|---|
| M13.0 | `write_dat` 加回讀驗證（暫存 → 驗證 → 原子替換） | `nbtio/`，獨立 commit |
| M13.1 | denylist 補強 + 世界指紋納入 `entities/` | 前置，各自獨立可測 |
| M13.2 | `scan/registry.py` + region 來源改註冊表形式 | **純重構，行為不變**，既有測試守著 |
| M13.3 | `scan/sources/item.py`（兩套格式 + 遞迴）→ 接進 region | 這個範圍裡最大的一塊 |
| M13.4 | `scan/sources/entities.py` + 寫入層 entities 路徑 | `write/` 獨立 commit |
| M13.5 | `scan/sources/level_dat.py` + `write/datfile_apply.py` | `write/` 獨立 commit |
| M13.6 | `scan/sources/scoreboard.py` | 共用 M13.5 的寫入器 |
| M13.7 | `scan/sources/datapack.py` + `write/datapack_apply.py` | `write/` 獨立 commit |
| M13.8 | 已在地化跳過 | |
| M13.9 | 真實地圖驗證 + 文件寫回 | |

---

## 9. 測試

* 每個來源一個單元測試檔，走真實的 NBT 結構而不是 mock。
* **fixture 一律取自自建探測世界**（授權考量，見 M3 的同一條決定）。要新增：
  `entities/*.mca` 的切片、`scoreboard.dat`。`level.dat` 的 fixture 已經有。
* **M12 的端到端測試擴充涵蓋新來源**——那份測試的價值就在於它會抓到「某一層漂移
  之後整條鏈安靜地斷掉」，新增六個來源之後更需要它。
* denylist 的三項修正各自要有一條會紅的測試（`LastOutput/text` 現在是通過的）。
* **真實地圖驗證是完成的條件之一**，不是加分：三張語料地圖各跑一次 extract，
  比對抽出的單位數與清點的相異數對得上。

---

## 10. 明確不做

| 項目 | 理由 |
|---|---|
| 指令方塊的 `Command` | 需要指令語法解析。架構計畫的「不做」清單已列 |
| datapack `.mcfunction` | 同上。MP2 有 2,613 個 |
| 翻譯地圖自己的 lang 檔 | 另一個里程碑的工作量，會把 `%1$s` 格式參數一起拉進來 |
| `poi/*.mca` | 沒有文字 |
| 玩家檔 `playerdata/*.dat` | 單人地圖的玩家背包已在 `level.dat` 的 `Data.Player`；多人伺服器的存檔不是 v1 的對象 |
