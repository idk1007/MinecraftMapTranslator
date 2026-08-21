# SPDX-License-Identifier: GPL-3.0-or-later
"""M8 字寬校準（可重跑）。

    # ① 產生校準用的告示牌（改寫你放好的空白告示牌）
    python tools/calibrate_font_widths.py "sandbox/<世界>"

    # ② 進遊戲看完之後回填
    python tools/calibrate_font_widths.py --record \\
        --sign-ascii-max 15 --sign-cjk-max 10 \\
        --hanging-ascii-max 10 --hanging-cjk-max 6

**為什麼是「改寫你放好的空白告示牌」而不是產生 `/setblock` 指令**：這個工具從來不
碰方塊，只碰方塊實體裡的文字（`write_region` 那條已經驗過的路）。要它去生成一串
`/setblock` 就得猜 1.21.11 的方塊實體 NBT 語法，而猜錯的症狀是「進遊戲什麼都沒出現」
——白跑一趟。改寫既有告示牌用的是我們自己測過的寫入路徑，最壞情況是文字寫錯，看得見。

這也是 `tools/m4_prepare.py` 用過的做法（挑本來就空白的告示牌，看到的任何東西都
確定是我們造成的）。

---

## 你要先做的（一分鐘）

在 sandbox 之外的創造模式世界裡，找一片平地：

* 放 **5 面一般告示牌**（`oak_sign` 之類，正反面都要空白）
* 放 **4 面吊掛告示牌**（`oak_hanging_sign` 之類）

排成一列、面朝同一邊最好認。存檔離開，然後 `mcmt sandbox import` 進來。

## 兩種量測同時做

**階梯**：第 N 行放 N 個同樣的字。你走過去看「最後一行沒被截掉的是第幾行」，
回報兩三個數字就好。抓的是**臨界點**。

**校準板**：放已知組成的參考字串（`iiiiiiiiii`、`中中中中中`、粗體的 `MMMMMMMMMM`
之類）。你截圖丟回來，可以從圖上量出每一類字的實際 px 寬。抓的是**精確值**。

一次跑**兩種都會排進去**，不必選：階梯佔大部分的行，校準板佔每一種的最後八行。
階梯給臨界點、校準板給精確值，兩者對不上就代表某張表記錯了——那正是要兩種都做的
理由（單靠階梯，ASCII 表錯了你不會知道）。

---

## 回填之後會發生什麼

`--record` 只重寫 `src/mcmt/fontdata/vanilla_v1.json`：把 `calibrated` 翻成 true、
`evidence` 改成 `遊戲實測`、並把**你回報的原始觀察**一起記進去，讓推導過程之後
查得到。旗標翻成 true 之後 `enforcement` 才會從 `warn` 升成 `error`——那條規則在
`mcmt/width.py`，有測試守著。
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import amulet_nbt  # noqa: E402

from mcmt.nbtio.compression import decompress_chunk  # noqa: E402
from mcmt.nbtio.region import ChunkWrite, read_region, region_files, write_region  # noqa: E402
from mcmt.safety.backup import BackupSet  # noqa: E402
from mcmt.safety.paths import ensure_readable, ensure_writable  # noqa: E402
from mcmt.width import FONT_DATA  # noqa: E402

FONTDATA_PATH = Path(__file__).resolve().parent.parent / "src" / "mcmt" / "fontdata" / "vanilla_v1.json"

CJK = "中"
ASCII_WIDE = "M"  # 最寬的一般 ASCII 字母，6px
BOLD_BOARD_COUNT = 10  # 校準板第 7 行放幾個粗體 M。推導要知道「沒被截」長什麼樣
_FACES = ("front_text", "back_text")


def ladder(character: str, longest: int) -> list[str]:
    """第 N 行放 N 個同樣的字。行號就是字數，不必再寫標籤佔寬度。"""
    return [character * n for n in range(1, longest + 1)]


def board() -> list[str]:
    """截圖量測用的參考字串。**每一條的預期寬度都算得出來**，對不上就是表錯了。

    窄字（`i` 2px、`l` 3px、`t` 4px）特別重要：那幾個是 ASCII 表裡最容易記錯的值，
    而它們錯了會讓「這行放得下幾個字」在英文短語上整個偏掉。
    """
    return [
        ASCII_WIDE * 10,   # 期望 60px
        "i" * 10,          # 期望 20px
        "l" * 10,          # 期望 30px
        "t" * 10,          # 期望 40px
        CJK * 5,           # 期望 45px（CJK 9px 的話）
        "MiMiMiMiMi",      # 期望 40px：混合排版，驗加總不是近似
        "§l" + ASCII_WIDE * 10,  # 期望 70px：粗體每字 +1
        "0123456789",      # 期望 60px：數字與字母同寬
    ]


def lines_for(kind: str) -> list[tuple[str, str]]:
    """`(標籤, 文字)`。標籤只印在終端機上，不佔告示牌的寬度。"""
    longest_ascii = 18 if kind == "sign" else 13
    longest_cjk = 12 if kind == "sign" else 9
    rows = [(f"階梯 ASCII {n + 1}", t) for n, t in enumerate(ladder(ASCII_WIDE, longest_ascii))]
    rows += [(f"階梯 CJK {n + 1}", t) for n, t in enumerate(ladder(CJK, longest_cjk))]
    rows += [(f"校準板 {n + 1}", t) for n, t in enumerate(board())]
    return rows


def is_blank_face(face) -> bool:
    if not isinstance(face, amulet_nbt.CompoundTag):
        return False
    messages = face.get("messages")
    if not isinstance(messages, amulet_nbt.ListTag):
        return False
    return all(_is_blank(m) for m in messages)


def _is_blank(message) -> bool:
    if isinstance(message, amulet_nbt.StringTag):
        return str(message) in ("", '""')
    if isinstance(message, amulet_nbt.CompoundTag):
        return all(str(v) == "" for v in message.values())
    return False


def kind_of(block_id: str) -> str | None:
    if "hanging_sign" in block_id:
        return "hanging_sign"
    if "sign" in block_id:
        return "sign"
    return None


def collect_blank_signs(world: Path):
    """走過整個世界，找出空白的告示牌面。回傳依座標排序的清單。"""
    found = []
    for region_path in region_files(ensure_readable(world)):
        for raw in read_region(region_path):
            if raw.is_external:
                continue
            root = amulet_nbt.load(
                decompress_chunk(raw.payload, raw.compression_type, chunk_index=raw.index),
                compressed=False,
            ).compound
            entities = root.get("block_entities")
            if not isinstance(entities, amulet_nbt.ListTag):
                continue
            for position, entity in enumerate(entities):
                if not isinstance(entity, amulet_nbt.CompoundTag):
                    continue
                kind = kind_of(str(entity.get("id", "")))
                if kind is None:
                    continue
                for face in _FACES:
                    if is_blank_face(entity.get(face)):
                        found.append(
                            {
                                "region": str(region_path),
                                "chunk": raw.index,
                                "entity": position,
                                "face": face,
                                "kind": kind,
                                "x": int(entity["x"]),
                                "y": int(entity["y"]),
                                "z": int(entity["z"]),
                            }
                        )
    # 正面排在背面前面：讀的人是先看到正面的。字母序會把 back_text 排到前面去。
    found.sort(
        key=lambda f: (f["kind"], f["x"], f["z"], f["y"], 0 if f["face"] == "front_text" else 1)
    )
    return found


def prepare(world: Path) -> int:
    faces = collect_blank_signs(world)
    by_kind = {"sign": [], "hanging_sign": []}
    for face in faces:
        by_kind[face["kind"]].append(face)

    plan = {}
    shortfall = []
    for kind, rows in (("sign", lines_for("sign")), ("hanging_sign", lines_for("hanging_sign"))):
        available = by_kind[kind]
        needed = (len(rows) + 3) // 4
        if len(available) < needed:
            shortfall.append((kind, needed, len(available)))
        for index, face in enumerate(available[:needed]):
            plan[(face["region"], face["chunk"], face["entity"], face["face"])] = (
                face,
                rows[index * 4 : index * 4 + 4],
            )

    if shortfall:
        for kind, needed, have in shortfall:
            print(
                f"{kind}：需要 {needed} 個空白面（一面告示牌正反各算一個），只找到 {have}",
                file=sys.stderr,
            )
        print("在世界裡多放幾面空白告示牌再跑一次。", file=sys.stderr)
        return 2

    written = _write(world, plan)

    print(f"世界：{world}")
    print(f"改寫的告示牌面：{len(plan)}（改動 {written} 個 chunk）")
    print()
    for (region, chunk, entity, face), (info, rows) in sorted(
        plan.items(),
        key=lambda item: (
            item[1][0]["kind"],
            item[1][0]["x"],
            item[1][0]["z"],
            0 if item[1][0]["face"] == "front_text" else 1,
        ),
    ):
        side = "正面" if face == "front_text" else "背面"
        print(f"  {info['kind']} {side}  /tp @s {info['x']} {info['y'] + 1} {info['z']}")
        for line, (label, text) in enumerate(rows, start=1):
            print(f"      第 {line} 行  {label:<14} {text}")
    print()
    print("進遊戲之後要回報的四個數字（見 docs/m8-checklist.md）：")
    print("  一般告示牌：最後一行完整顯示的 ASCII 階梯是第幾行、CJK 階梯是第幾行")
    print("  吊掛告示牌：同樣兩個數字")
    print("順便對每一種的校準板截一張圖——那是精確值的來源。")
    return 0


def _write(world: Path, plan) -> int:
    """逐 region 改寫。未被改到的 chunk 原封複製原始壓縮位元組。"""
    import zlib
    from collections import defaultdict

    by_region = defaultdict(list)
    for (region, chunk, entity, face), value in plan.items():
        by_region[region].append((chunk, entity, face, value[1]))

    touched = 0
    with BackupSet(world) as backup:
        for region_path, items in by_region.items():
            path = Path(region_path)
            original = list(read_region(ensure_readable(path)))
            payloads = {}
            for chunk_index in {c for c, _, _, _ in items}:
                raw = next(c for c in original if c.index == chunk_index)
                root = amulet_nbt.load(
                    decompress_chunk(raw.payload, raw.compression_type, chunk_index=raw.index),
                    compressed=False,
                ).compound
                for c, entity_index, face, rows in items:
                    if c != chunk_index:
                        continue
                    entity = root["block_entities"][entity_index]
                    entity[face]["messages"] = amulet_nbt.ListTag(
                        [
                            amulet_nbt.CompoundTag({"text": amulet_nbt.StringTag(text)})
                            for _, text in rows
                        ]
                        + [
                            amulet_nbt.CompoundTag({"text": amulet_nbt.StringTag("")})
                            for _ in range(4 - len(rows))
                        ]
                    )
                payloads[chunk_index] = zlib.compress(
                    amulet_nbt.NamedTag(root, "").save_to(compressed=False)
                )
                touched += 1

            backup.protect(path)
            write_region(
                ensure_writable(path),
                [
                    ChunkWrite.replaced(c, payloads[c.index])
                    if c.index in payloads
                    else ChunkWrite.unchanged(c)
                    for c in original
                ],
            )
        print(f"備份：{backup.directory}（{backup.file_count} 個檔案）")
    return touched


def _cjk_range(ascii_max: int, cjk_max: int, ascii_advance: int) -> set[int]:
    """從一組臨界點推出 CJK 前進寬度**可能的整數區間**。

    階梯只給得出區間，給不出單一值，這是它的性質不是缺陷：`ascii_max` 個 'M' 進得去
    而 `ascii_max + 1` 進不去，只說明真正的預算 B 落在 `[Ka·A, (Ka+1)·A)`。同理
    `Kc` 個 CJK 進得去、`Kc+1` 個進不去，只說明 `Kc·adv ≤ B < (Kc+1)·adv`。

    所以正確的做法是**兩種告示牌各推一個區間再取交集**，而不是各算一個整數再要求
    相等——後者幾乎一定不相等（兩邊的無條件捨去落點不同），會把一組其實一致的
    觀察判成錯誤。那種假警報比沒有檢查更糟：跑幾次都紅之後，人就會開始繞過它。
    """
    lowest_budget = ascii_max * ascii_advance
    highest_budget = (ascii_max + 1) * ascii_advance - 1
    lower = lowest_budget / (cjk_max + 1)  # 嚴格大於
    upper = highest_budget / cjk_max  # 小於等於
    return {n for n in range(1, 33) if lower < n <= upper}


def _bold_extra_candidates(
    observations: dict, ascii_advance: int, shown: dict, cjk_advance: int
) -> set[int]:
    """粗體讓每個字多幾 px。

    校準板第 7 行固定放 10 個粗體 M，所以觀察分兩種，給的約束不一樣：

    * **看到 10 個**（沒被截）→ 只知道 `10·(A+e) ≤ B`，是下界。
    * **看到 N < 10 個**（被截）→ `N·(A+e) ≤ B < (N+1)·(A+e)`，是夾擠，資訊多得多。

    [遊戲實測 2026-08-21] 一般告示牌 10 個全顯示、吊掛只顯示 8 個——**吊掛那個被截
    的觀察才是把 e 釘死的那一個**。若 e 是 0，10 個粗體 M 就和 10 個一般 M 一樣寬，
    在吊掛上會全部顯示；它沒有，所以粗體確實會加寬。

    **三個觀察要一起解，不能只看 ASCII 那一個。** 第一版漏掉 CJK，於是 e=2 也留了
    下來——它要求吊掛的預算落在 64..65px，而同一面上「6 個中文字進得去、7 個不行」
    要求預算 < 63px。兩者其實互斥，只是分開檢查看不出來。
    """
    candidates = set()
    for extra in range(0, 4):
        advance = ascii_advance + extra
        if all(
            _budgets_for(kind, observations, ascii_advance, cjk_advance, shown, advance)
            for kind in observations
        ):
            candidates.add(extra)
    return candidates


def _budgets_for(
    kind: str,
    observations: dict,
    ascii_advance: int,
    cjk_advance: int,
    shown: dict,
    bold_advance: int | None = None,
) -> list[int]:
    """同時滿足這一種告示牌**全部**觀察的預算值。空的代表這組參數不成立。"""
    ascii_max, cjk_max = observations[kind]
    seen = shown.get(kind)
    result = []
    for budget in range(ascii_max * ascii_advance, (ascii_max + 1) * ascii_advance):
        if not cjk_max * cjk_advance <= budget < (cjk_max + 1) * cjk_advance:
            continue
        if seen is not None and bold_advance is not None:
            if seen >= BOLD_BOARD_COUNT:
                if not seen * bold_advance <= budget:
                    continue
            elif not seen * bold_advance <= budget < (seen + 1) * bold_advance:
                continue
        result.append(budget)
    return result


def record(args) -> int:
    """把觀察到的臨界點換算成量測表。**推導過程一起寫進檔案。**"""
    ascii_advance = args.ascii_advance
    data = json.loads(FONTDATA_PATH.read_text("utf-8"))

    observations = {
        "sign": (args.sign_ascii_max, args.sign_cjk_max),
        "hanging_sign": (args.hanging_ascii_max, args.hanging_cjk_max),
    }

    derived_cjk = {}
    for kind, (ascii_max, cjk_max) in observations.items():
        if ascii_max is None or cjk_max is None:
            continue
        # 預算落在 [k*A, (k+1)*A)。取下界是**保守**的：寧可少報空間，也不要答應
        # 一個其實放不下的字數。
        budget = ascii_max * ascii_advance
        data["budgets"][kind].update(
            {
                "max_width_px": budget,
                "calibrated": True,
                "evidence": "遊戲實測",
                "note": (
                    f"[遊戲實測 {date.today().isoformat()}] {ascii_max} 個 '{ASCII_WIDE}'"
                    f"（{ascii_advance}px）完整顯示、{ascii_max + 1} 個被截掉，"
                    f"因此預算取下界 {budget}px。同一面上 {cjk_max} 個 CJK 字完整顯示。"
                ),
                "observed": {
                    "ascii_max": ascii_max,
                    "cjk_max": cjk_max,
                    "ascii_advance": ascii_advance,
                },
            }
        )
        derived_cjk[kind] = _cjk_range(ascii_max, cjk_max, ascii_advance)

    if args.cjk_advance is not None:
        data["cjk_advance"] = args.cjk_advance
        data["advance_evidence"]["cjk"] = "遊戲實測"
    elif derived_cjk:
        candidates = set.intersection(*derived_cjk.values())
        if not candidates:
            print(
                f"兩種告示牌推出來的 CJK 寬度湊不到交集："
                f"{ {k: sorted(v) for k, v in derived_cjk.items()} }。"
                f"這代表 ASCII 表或某個臨界點記錯了——**沒有回填**，"
                f"請用校準板的截圖直接量一次，再用 --cjk-advance 指定。",
                file=sys.stderr,
            )
            return 2
        # **取交集裡最大的**：CJK 越寬，一行放得下的字越少。少報空間是安全的，
        # 多報會讓譯者照著寫然後在遊戲裡被截掉。
        data["cjk_advance"] = max(candidates)
        data["advance_evidence"]["cjk"] = "遊戲實測"
        if len(candidates) > 1:
            print(
                f"CJK 寬度只縮到 {sorted(candidates)}，取了最保守的 {max(candidates)}。"
                f"要確定值就用校準板的截圖量一次，再 --cjk-advance 指定。"
            )

    if args.ascii_advance != FONT_DATA["default_advance"]:
        data["default_advance"] = ascii_advance
        data["advance_evidence"]["ascii"] = "遊戲實測"

    shown = {
        "sign": args.sign_bold_shown,
        "hanging_sign": args.hanging_bold_shown,
    }
    if any(v is not None for v in shown.values()):
        extras = _bold_extra_candidates(
            observations, ascii_advance, shown, data["cjk_advance"]
        )
        if not extras:
            print(
                "粗體的觀察和階梯對不上——**沒有回填**。"
                "先確認校準板第 7 行看到的個數是不是數錯了。",
                file=sys.stderr,
            )
            return 2
        if len(extras) == 1:
            data["bold_extra"] = extras.pop()
            data["advance_evidence"]["bold"] = "遊戲實測"
            data["bold_observed"] = {
                k: v for k, v in shown.items() if v is not None
            } | {"board_count": BOLD_BOARD_COUNT}
        else:
            print(
                f"粗體加寬只縮到 {sorted(extras)}，維持原值 {data['bold_extra']}"
                f"（{data['advance_evidence']['bold']}）。"
                f"要釘死它，需要一行粗體在某一種告示牌上被截斷。"
            )

    data["calibrated_at"] = date.today().isoformat()
    data["scale_note"] = (
        "階梯觀察定的是**比例**，不是絕對 px——滿足這組觀察的解全部是等比族"
        "（ASCII:CJK 恆為 2:3），把整張表乘以 2 也一樣相容。絕對尺度來自"
        " ascii_advance 這個 [文件] 級的錨。工具真正用到的 cjk_capacity"
        "（一行放得下幾個中文字）只依賴比值，所以就算尺度整體錯了，那個數字仍然是對的。"
    )
    FONTDATA_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"已回填：{FONTDATA_PATH}")
    print(f"  CJK 前進寬度：{data['cjk_advance']}px（{data['advance_evidence']['cjk']}）")
    print(f"  粗體加寬：{data['bold_extra']}px（{data['advance_evidence']['bold']}）")
    for kind in observations:
        budget = data["budgets"][kind]
        print(
            f"  {kind}：{budget['max_width_px']}px"
            f"（約 {budget['max_width_px'] // data['cjk_advance']} 個中文字）"
            f"{'（已校準）' if budget['calibrated'] else '（仍未校準）'}"
        )
    print()
    print("接下來：跑一次 pytest。`enforcement` 會自動從 warn 變成 error，")
    print("而 tests/unit/test_width.py 有幾條測試綁著目前的數字——它們變紅是預期的，")
    print("要照新的量測值改，不是把測試放寬。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("world", nargs="?", help="sandbox 底下的世界資料夾")
    parser.add_argument("--record", action="store_true", help="回填量測結果")
    parser.add_argument("--sign-ascii-max", type=int)
    parser.add_argument("--sign-cjk-max", type=int)
    parser.add_argument("--hanging-ascii-max", type=int)
    parser.add_argument("--hanging-cjk-max", type=int)
    parser.add_argument(
        "--ascii-advance",
        type=int,
        default=FONT_DATA["default_advance"],
        help=f"'{ASCII_WIDE}' 的前進寬度，預設 {FONT_DATA['default_advance']}px（[文件]）",
    )
    parser.add_argument(
        "--cjk-advance",
        type=int,
        help="直接指定 CJK 前進寬度（從校準板截圖量出來的值）。不給就從臨界點推導",
    )
    parser.add_argument(
        "--sign-bold-shown",
        type=int,
        help=f"一般告示牌的校準板第 7 行（{BOLD_BOARD_COUNT} 個粗體 M）看得到幾個",
    )
    parser.add_argument("--hanging-bold-shown", type=int, help="吊掛告示牌的同一行")
    args = parser.parse_args()

    if args.record:
        return record(args)
    if not args.world:
        parser.error("要產生校準告示牌就給一個世界資料夾，要回填就加 --record")
    return prepare(Path(args.world).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
