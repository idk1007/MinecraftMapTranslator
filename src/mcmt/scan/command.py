# SPDX-License-Identifier: GPL-3.0-or-later
"""指令字串裡的可翻文字——白名單動詞、execute 剝除、L1/L2/L3。

這是一個**共用的純函式模組**，不自己走訪 chunk。`scan/sources/region.py` 與
`scan/sources/entities.py` 在既有的「走訪一個 block entity／entity」函式裡呼叫
`scan_command_string()`；`scan/sources/mcfunction.py` 對每一行（已排除延續行）
也呼叫它。三處共用同一份白名單、同一份 L3 偵測邏輯，不是巧合的重複——理由跟
`scan/sources/item.py` 被三處共用一樣：漏掉一層是最短的出錯路徑。

見 docs/superpowers/specs/2026-09-05-command-text-design.md §2、§3。
"""

from collections import Counter
from typing import Any, Iterator

import amulet_nbt

from mcmt.model.node import NodePath, decode_step
from mcmt.scan.node import TextNode
from mcmt.scan.sources.datapack import _to_amulet
from mcmt.tree.codecs import codec_for
from mcmt.tree.span_locator import (
    LocateError,
    _split_top_level,
    find_balanced_span,
    find_unquoted_token,
    locate_path_span,
)

__all__ = ["LINE_CONTINUES", "scan_command_string"]

LINE_CONTINUES = "line_continuation"

_SAY_VERBS = ("say", "me")
_CLICK_ACTIONS = {"run_command", "suggest_command"}
_COMPONENT_VERBS = {"tellraw", "title", "bossbar", "scoreboard", "data", "give", "item"}


def scan_command_string(
    text: str, *, base_path: NodePath, anchor: dict[str, Any] | None, stats: Counter
) -> Iterator[TextNode]:
    """給一條**已確定不是延續行**的指令文字，yield 白名單動詞找到的文字節點。"""
    inner, offset = _strip_execute(text)
    stripped = inner.lstrip()
    lead = len(inner) - len(stripped)
    verb, rest = _split_first_token(stripped)
    if verb is None:
        stats["skipped_command_unsupported_shape"] += 1
        return

    if verb in _SAY_VERBS:
        payload = rest.lstrip()
        if not payload:
            stats["skipped_command_unsupported_shape"] += 1
            return
        # `say`/`me` 沒有 component/SNBT 包裝層，但**仍然需要兩個** decode
        # 步驟，不是一個：第一步固定是 `("command", (0, len(text)))`——跟其他
        # 每個動詞經過 `_yield_tag` 產生的第一步完全一樣，`write/common.py`
        # 的 `_command_length_matches` 靠這個固定第一步的 span 快速判斷「指令
        # 字串長度跟 extract 當下是否一致」，寫死假設它一定是第一步；只給一步
        # 且把它的 span 換成 payload 自己的位置（start > 0）會讓那個檢查誤判
        # 長度不對，把每一筆 `command_say_text` 的 edit 都當成「世界被改過」
        # 拒寫，連 splice 都碰不到。第二步（最後一步）才是真正的 splice
        # 目標——payload 自己在原始文字裡的絕對位置。少了這一步，node_path 會
        # 以 `key_step("Command")` 收尾，write 層的 decode-dispatch 分支
        # 認不出它，落到舊的整值替換路徑，把 `say `／`me ` 前綴一起換掉，寫壞
        # 指令方塊。
        absolute_start = offset + lead + (len(stripped) - len(payload))
        node_path = base_path.child(
            decode_step("command", span=(0, len(text)))
        ).child(decode_step("command", span=(absolute_start, len(text))))
        yield TextNode(
            path=node_path,
            tag=amulet_nbt.StringTag(payload),
            category="command_say_text",
            anchor=anchor,
        )
        return

    if verb == "tellraw":
        target, arg_text = _split_first_token(rest)
        if target is None:
            stats["skipped_command_unsupported_shape"] += 1
            return
        yield from _locate_and_yield(
            text, arg_text, offset, lead, stripped, base_path, anchor, stats
        )
        return

    if verb == "title":
        target, remainder = _split_first_token(rest)
        slot, arg_text = _split_first_token(remainder)
        if slot not in ("title", "subtitle", "actionbar"):
            stats["skipped_command_unsupported_shape"] += 1
            return
        yield from _locate_and_yield(
            text, arg_text, offset, lead, stripped, base_path, anchor, stats
        )
        return

    if verb == "bossbar":
        sub, remainder = _split_first_token(rest)
        bar_id, remainder2 = _split_first_token(remainder)
        field, arg_text = _split_first_token(remainder2)
        if sub != "set" or field != "name":
            stats["skipped_command_unsupported_shape"] += 1
            return
        yield from _locate_and_yield(
            text, arg_text, offset, lead, stripped, base_path, anchor, stats
        )
        return

    if verb == "scoreboard":
        sub, remainder = _split_first_token(rest)
        action, remainder2 = _split_first_token(remainder)
        if sub != "objectives" or action != "add":
            stats["skipped_command_unsupported_shape"] += 1
            return
        # <name> <criteria> [<displayname>] —— 顯示名稱是可選的第三個 token。
        _, remainder3 = _split_first_token(remainder2)
        _, arg_text = _split_first_token(remainder3)
        if not arg_text.strip():
            return  # 沒有顯示名稱，這條指令沒有文字，不是錯誤。
        yield from _locate_and_yield(
            text, arg_text, offset, lead, stripped, base_path, anchor, stats
        )
        return

    if verb == "data":
        yield from _scan_data_command(
            text, rest, offset, lead, stripped, base_path, anchor, stats
        )
        return

    if verb in ("give", "item"):
        idx = text.find("[", offset + lead)
        if idx == -1:
            stats["skipped_command_unsupported_shape"] += 1
            return
        try:
            bracket_span = find_balanced_span(text, idx)
        except LocateError:
            stats["skipped_command_unsupported_shape"] += 1
            return
        component_span = _find_component(bracket_span, text, "custom_name")
        if component_span is None:
            stats["skipped_command_unsupported_shape"] += 1
            return
        yield from _yield_snbt_span(text, component_span, base_path, anchor, stats)
        return

    stats["skipped_command_unsupported_shape"] += 1


def _locate_and_yield(
    text: str,
    arg_text: str,
    offset: int,
    lead: int,
    stripped: str,
    base_path: NodePath,
    anchor: dict[str, Any] | None,
    stats: Counter,
) -> Iterator[TextNode]:
    if not arg_text.strip():
        stats["skipped_command_unsupported_shape"] += 1
        return
    arg_start_in_stripped = len(stripped) - len(arg_text.lstrip())
    absolute_start = offset + lead + arg_start_in_stripped
    try:
        arg_span = find_balanced_span(text, absolute_start)
    except LocateError:
        stats["skipped_command_unsupported_shape"] += 1
        return
    yield from _yield_component(
        text, arg_span, base_path=base_path, anchor=anchor, stats=stats
    )


def _yield_component(
    text: str,
    arg_span: tuple[int, int],
    *,
    base_path: NodePath,
    anchor: dict[str, Any] | None,
    stats: Counter,
) -> Iterator[TextNode]:
    """把 `arg_span`（一段 JSON 文字，L1 動詞的引數）解碼成 amulet_nbt 樹，套
    L3 檢查後 yield。"""
    raw = text[arg_span[0] : arg_span[1]]
    try:
        value = codec_for("json_component").decode(raw)
    except Exception:
        stats["skipped_command_unsupported_shape"] += 1
        return
    tag = _to_amulet(value)
    yield from _yield_tag(
        text, [("json_component", arg_span)], tag, base_path, anchor, stats
    )


def _yield_snbt_span(
    text: str,
    span: tuple[int, int],
    base_path: NodePath,
    anchor: dict[str, Any] | None,
    stats: Counter,
) -> Iterator[TextNode]:
    """把 `span`（一段 SNBT 文字，`give`/`item` 物品組件的引數）解碼成
    amulet_nbt 樹，套 L3 檢查後 yield。"""
    raw = text[span[0] : span[1]]
    try:
        tag = codec_for("snbt").decode(raw)
    except Exception:
        stats["skipped_command_unsupported_shape"] += 1
        return
    yield from _yield_tag(text, [("snbt", span)], tag, base_path, anchor, stats)


def _yield_tag(
    text: str,
    steps: list[tuple[str, tuple[int, int]]],
    tag: Any,
    base_path: NodePath,
    anchor: dict[str, Any] | None,
    stats: Counter,
    category: str = "command_component_text",
) -> Iterator[TextNode]:
    """通用收尾：L3 檢查、空文字檢查，組 `node_path` 並 yield。四個呼叫端
    （L1 的 `_yield_component`、`give`/`item` 的 `_yield_snbt_span`、L2 的
    `_yield_message` 的兩個分支）共用同一份收尾邏輯。

    `steps` 是接在 `("command", 整條文字)` 這個固定第一步之後的 decode 步驟
    序列，`(codec_name, span)` 依序排列。**大多數呼叫端只有一步**（這段文字
    只被解碼過一次）；`_yield_message` 的「SNBT 字串包裝 JSON」分支需要兩步
    ——先標記「這裡進了一層 SNBT」（span 是整個 SNBT 引數，不是這個 leaf
    自己的位置，純粹記錄「此處是 SNBT 方言」這件事，不是 splice 目標），再
    標記「這裡面的字串內容又被當 JSON 解了一次」（span 才是這個 leaf 自己的
    位置，是真正的 splice 目標）。`NodePath.last_span`／`span_order()` 只看
    **最後一個** decode 步驟的 span，所以不管 steps 有幾個，排序用的座標永遠
    是最後一步、也就是這個 leaf 自己的位置，不會被中間那個「純標記用」的步驟
    污染。

    `category` 預設是 `command_component_text`（走 translate key）。唯一的例外
    是 `_yield_message` 的裸字串分支——見那裡的說明，它必須走 in_place。"""
    if _has_nested_command_reference(tag):
        stats["skipped_command_nested_reference"] += 1
        return
    if _contains_translate(tag):
        # component 樹裡任何一處參照到別的在地化系統（地圖自己的 lang key，或
        # 原版 key）——重建時我們的 key 會蓋掉它，把一張支援多語言的地圖靜默
        # 降級成只支援我們寫進去的那一種。與 region 路徑的 M13b 守門同一個判準、
        # 同一個計數器（`extract/build.py` 的 `_contains_translate`）。
        stats["skipped_already_localised"] += 1
        return
    if _is_empty_text(tag):
        stats["skipped_empty"] += 1
        return
    node_path = base_path.child(decode_step("command", span=(0, len(text))))
    for codec_name, span in steps:
        node_path = node_path.child(decode_step(codec_name, span=span))
    yield TextNode(path=node_path, tag=tag, category=category, anchor=anchor)


def _contains_translate(tag: Any) -> bool:
    """`tag`（或它任何一層子節點）裡有沒有 `translate` 節點。

    `extract/build.py` 的同名函式走的是**攤平後的 skeleton**，只認 `type ==
    "translate"` 與 `extra`。這裡走的是**還沒攤平的 amulet 樹**，而
    `data merge entity … {text:{…}}` 會把 `translate` 藏在 `text` 底下——那個
    `text` 是 text_display 的**欄位名**，不是文字 component 的 `text` 鍵，攤平
    器不會鑽進去，於是下游那道守門看不到它。所以這裡遞迴進每一個 compound／
    list 子節點，任何一處中了就算。判準與後果的說明見 CLAUDE.md
    「component 樹（extra）不是「原封搬運」」一節末尾的 M13b 註記。
    """
    if isinstance(tag, amulet_nbt.CompoundTag):
        if "translate" in tag:
            return True
        return any(_contains_translate(value) for value in tag.values())
    if isinstance(tag, amulet_nbt.ListTag):
        return any(_contains_translate(value) for value in tag)
    return False


def _is_empty_text(tag: Any) -> bool:
    """`tag` 是不是一個「沒有可翻文字」的空節點——空字串，或只有一個空
    `text` 鍵、沒有 `extra` 的 compound（`{text:""}`，告示牌空白行常見的
    寫法）。"""
    if isinstance(tag, amulet_nbt.StringTag):
        return not str(tag)
    if isinstance(tag, amulet_nbt.CompoundTag):
        text_value = tag.get("text")
        extra = tag.get("extra")
        if isinstance(text_value, amulet_nbt.StringTag) and not str(text_value) and not extra:
            return True
    return False


_SIGN_FACES = ("front_text", "back_text")


def _scan_data_command(
    text: str,
    rest: str,
    offset: int,
    lead: int,
    stripped: str,
    base_path: NodePath,
    anchor: dict[str, Any] | None,
    stats: Counter,
) -> Iterator[TextNode]:
    sub, remainder = _split_first_token(rest)
    if sub == "merge":
        # data merge block|entity|storage <target...> <nbt>
        _, after_kind = _split_first_token(remainder)
        arg_text = _skip_to_nbt_argument(after_kind)
        if arg_text is None:
            stats["skipped_command_unsupported_shape"] += 1
            return
        arg_start_in_stripped = len(stripped) - len(arg_text.lstrip())
        absolute_start = offset + lead + arg_start_in_stripped
        yield from _scan_snbt_argument(text, absolute_start, base_path, anchor, stats)
        return

    if sub == "modify":
        idx = find_unquoted_token(text, 0, " merge value ")
        if idx == -1:
            stats["skipped_command_unsupported_shape"] += 1
            return
        arg_start = idx + len(" merge value ")
        yield from _scan_snbt_argument(text, arg_start, base_path, anchor, stats)
        return

    stats["skipped_command_unsupported_shape"] += 1


def _skip_to_nbt_argument(remainder: str) -> str | None:
    """`data merge block ~ ~ ~ {...}` 的 `<目標>` 部分長度不固定（座標、UUID、
    路徑都可能），但 NBT 引數永遠是**最後一段、以 `{` 開頭**的東西——直接找
    第一個 `{` 就是引數起點，不用去數前面有幾個 token。"""
    idx = remainder.find("{")
    return remainder[idx:] if idx != -1 else None


def _scan_snbt_argument(
    text: str,
    absolute_start: int,
    base_path: NodePath,
    anchor: dict[str, Any] | None,
    stats: Counter,
) -> Iterator[TextNode]:
    try:
        arg_span = find_balanced_span(text, absolute_start)
    except LocateError:
        stats["skipped_command_unsupported_shape"] += 1
        return
    raw = text[arg_span[0] : arg_span[1]]
    try:
        document = codec_for("snbt").decode(raw)
    except Exception:
        stats["skipped_command_unsupported_shape"] += 1
        return

    candidates: list[tuple[list[str], Any]] = []
    if isinstance(document, amulet_nbt.CompoundTag):
        for face in _SIGN_FACES:
            side = document.get(face)
            if isinstance(side, amulet_nbt.CompoundTag):
                messages = side.get("messages")
                if isinstance(messages, amulet_nbt.ListTag):
                    candidates.append(([face, "messages"], messages))
        # `data merge`／`data modify ... merge value` 常常已經被前面的目標路徑
        # （例如 `front_text.messages[0]`）縮小到只剩 messages 本身，這時 NBT
        # 引數不會再包一層 front_text/back_text——直接認 messages 這個鍵。
        top_messages = document.get("messages")
        if isinstance(top_messages, amulet_nbt.ListTag):
            candidates.append((["messages"], top_messages))

    found_any = False
    for path_prefix, messages in candidates:
        for index, message in enumerate(messages):
            try:
                leaf_span = locate_path_span(text, arg_span, [*path_prefix, index])
            except LocateError:
                continue
            found_any = True
            yield from _yield_message(
                text, arg_span, leaf_span, message, base_path, anchor, stats
            )

    if not found_any and isinstance(document, amulet_nbt.CompoundTag):
        # 不是告示牌形狀（例如 `merge value` 直接給的一個 component，或物品
        # 組件的 custom_name）——整段 SNBT 文件本身就是要翻的節點。
        yield from _yield_tag(text, [("snbt", arg_span)], document, base_path, anchor, stats)


def _yield_message(
    text: str,
    arg_span: tuple[int, int],
    leaf_span: tuple[int, int],
    message: Any,
    base_path: NodePath,
    anchor: dict[str, Any] | None,
    stats: Counter,
) -> Iterator[TextNode]:
    """一個 `messages[i]` 元素——可能是原生 SNBT compound（`{text:"..."}`），
    也可能是一個字串常值、內容剛好是一段跳脫過的 JSON（CLAUDE.md 二節的舊式
    JSON 形狀，只是這次出現在指令字串的 SNBT 裡而不是 chunk 的 NBT 裡）。

    兩種形狀記錄的 decode 步驟數不同：原生 compound 只需要一步
    `("snbt", leaf_span)`——這個節點本來就活在 SNBT 文件裡，沒有多一層編碼。
    字串包裝 JSON 需要兩步：`("snbt", arg_span)` 先標記「這裡是 SNBT 方言的
    地盤」（span 用整個 SNBT 引數，純粹標記方言、不是 splice 目標），再
    `("json_component", leaf_span)` 標記「這個字串常值的內容又被當 JSON 解了
    一次」（span 才是這個 leaf 自己的位置）。寫回層要分辨這兩種形狀——native
    的可以直接用 SNBT 語法序列化，字串包裝的要先跳脫成字串常值再 splice
    （design doc §4）——只看 decode 步驟數量／中間有沒有一個額外的 `snbt`
    標記步驟就能分辨，不需要另外存一個旗標。"""
    if isinstance(message, amulet_nbt.StringTag):
        content = str(message)
        try:
            value = codec_for("json_component").decode(content)
        except Exception:
            pass
        else:
            tag = _to_amulet(value)
            yield from _yield_tag(
                text,
                [("snbt", arg_span), ("json_component", leaf_span)],
                tag,
                base_path,
                anchor,
                stats,
            )
            return
        # 解不出 JSON——就是字面文字（例如 `data merge` 直接寫了一句沒有格式的
        # 文字），照原樣當一個 bare_string 節點，只有一層 SNBT。
        #
        # **這一支必須走 in_place（`command_say_text`），不能走 translate key。**
        # 它的兄弟元素還是字串（`messages:["Hello","","",""]`——一行字＋三行空，
        # 最常見的告示牌形狀），而 `TAG_List` 在 NBT 格式層帶單一元素型別 id：
        # 把 `{translate:…}` 放進去就是異質 list，遊戲的指令解析器吃不下，指令
        # 方塊寫得進磁碟卻再也跑不動，而報告會說 `unwritten: []`（CLAUDE.md 二節
        # 「NBT list 同型」；2026-09-06 的 C2）。
        #
        # 「沒有地方可以放 key，只能直接替換文字」正是 `command_say_text` 這個
        # category 在 `model/strategy.py` 的定義，也是 `draft_book_page` 的先例
        # ——所以這裡**重用**它而不是新增一個 category（不動合約、不 bump
        # SCHEMA_VERSION）。字串常值的內容怎麼換、譯文裡的引號與反斜線怎麼跳脫，
        # 是 `write/command_span.py::_compose_replacement` 那一格的事。
        #
        # 註：真正的告示牌 NBT 有「四行全部改寫」這條退路（`write/native.py::
        # apply_to_list` 會提升整個 list 並計 `list_promotions`）；指令字串裡沒有
        # ——那是一段**文字**，我們只在它上面做位移替換，沒有一棵 tag 可以整個
        # 重建。所以這裡只剩 in_place 一條路。
        yield from _yield_tag(
            text,
            [("snbt", leaf_span)],
            message,
            base_path,
            anchor,
            stats,
            category="command_say_text",
        )
        return
    yield from _yield_tag(text, [("snbt", leaf_span)], message, base_path, anchor, stats)


def _find_component(
    bracket_span: tuple[int, int], text: str, key: str
) -> tuple[int, int] | None:
    """`give`/`item` 的物品組件語法 `[key=value,key2=value2]` 用 `=` 分隔鍵值、
    逗號分隔多個組件、深度 0——跟 SNBT compound 的 `{key:value}` 語法不同
    （`locate_path_span` 認的是 `:`），所以不能直接複用它。物品組件永遠是
    `key=value` 用逗號分隔、深度 0，直接複用 `_split_top_level` 切逗號、自己
    找 `=` 就夠，不需要動 `span_locator.py` 已經測過的 `:` 分隔行為。"""
    start, end = bracket_span
    body = text[start + 1 : end - 1]
    for elem_start, elem_end in _split_top_level(body):
        piece = body[elem_start:elem_end]
        eq = piece.find("=")
        if eq == -1:
            continue
        if piece[:eq].strip() == key:
            value_start = start + 1 + elem_start + eq + 1
            value_end = start + 1 + elem_end
            return (value_start, value_end)
    return None


def _strip_execute(text: str) -> tuple[str, int]:
    """剝掉 `execute ... run ` 前綴，回傳 (剩下的指令文字, 它在原始 text 裡的
    起始位移)。沒有 `execute` 前綴就原樣回傳。"""
    stripped = text.lstrip()
    if not stripped.startswith("execute"):
        return text, 0
    idx = find_unquoted_token(text, 0, " run ")
    if idx == -1:
        return "", 0  # 只有條件、沒有 run——這條指令不執行任何東西，沒有文字。
    start = idx + len(" run ")
    return text[start:], start


def _has_nested_command_reference(tag: amulet_nbt.AbstractBaseTag) -> bool:
    """`tag`（或它的任何 extra 子節點）裡有沒有一個 click_event 指向另一條
    「白名單也認得出來、代表裡面還有文字」的指令。有 → 這整個 occurrence
    保守地整個跳過（方案 1 明確排除的 L3，見 spec §1）。"""
    if isinstance(tag, amulet_nbt.CompoundTag):
        click = tag.get("click_event")
        if isinstance(click, amulet_nbt.CompoundTag):
            action = str(click.get("action", ""))
            command = click.get("command")
            if action in _CLICK_ACTIONS and isinstance(command, amulet_nbt.StringTag):
                inner, _ = _strip_execute(str(command))
                verb, _ = _split_first_token(inner)
                if verb in _SAY_VERBS or verb in _COMPONENT_VERBS:
                    return True
        extra = tag.get("extra")
        if isinstance(extra, amulet_nbt.ListTag):
            for child in extra:
                if _has_nested_command_reference(child):
                    return True
    return False


def _split_first_token(text: str) -> tuple[str | None, str]:
    text = text.lstrip()
    if not text:
        return None, ""
    idx = text.find(" ")
    if idx == -1:
        return text, ""
    return text[:idx], text[idx + 1 :]
