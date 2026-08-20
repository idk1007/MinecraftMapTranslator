# SPDX-License-Identifier: GPL-3.0-or-later
"""舊式 JSON component 字串。

**compact 形式（分隔符不帶空格）就是 Mojang 寫出來的樣子。** [實測] 真實地圖的
78 個舊式 JSON 節點，用 `separators=(",", ":")` 重新編碼後 **78/78 位元組一致**；
用 `json.dumps` 的預設（帶空格）則 0/78 一致。

但那和 L2「重新壓縮後位元組一致」是同一類的**觀察**，不是保證——所以外科式寫入的
規則不變：沒被修改的節點根本不重新編碼。
"""

import json
from typing import Any

from mcmt.errors import CodecError

NAME = "json_component"
faithful_round_trip = True


def decode(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError as exc:
        raise CodecError(codec=NAME, detail=str(exc)) from exc


def encode(value: Any) -> str:
    # ensure_ascii=False：中文要保持字面，不是 \uXXXX。
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
