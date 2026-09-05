# SPDX-License-Identifier: GPL-3.0-or-later
"""指令字串——標記層，不做真正的解析。

真正的解析（白名單動詞、`execute` 前綴剝除、找出文字參數的範圍）在
`mcmt.scan.command`；把巢狀 SNBT/JSON 值組回可以 splice 的文字在
`mcmt.write.command_span`。這個 codec 只負責讓 `codec_for("command")` 不再
`raise NotImplementedError`——它存在的理由是合約的 `decode.codec` enum 允許
`"command"` 這個值，`node_path` 需要一個真的可以被 `codec_for()` 找到的名字，
但「指令字串」本身沒有一個值得解碼成的中介型別（不像 json_component 解碼成
component 樹），decode/encode 都是近乎透明的 identity。

見 docs/superpowers/specs/2026-09-05-command-text-design.md §3 對這個決定的
完整說明。
"""

NAME = "command"
faithful_round_trip = False


def decode(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError(f"command codec 只接受字串，收到 {type(text).__name__}")
    return text


def encode(value: str) -> str:
    return str(value)
