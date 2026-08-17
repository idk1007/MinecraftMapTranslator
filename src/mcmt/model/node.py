# SPDX-License-Identifier: GPL-3.0-or-later
"""節點路徑（M5.4）——從 chunk 根走到一個文字節點的完整指路。

三種步驟，對應合約的 `pathStep`：

    key      走進一個鍵
    index    走進 list 的第 n 個
    decode   **這裡以下是另一份文件**

`decode` 是三者裡意義最重的一個。它標記「父字串裡包著一份獨立編碼的文件」——
指令字串裡包 SNBT、SNBT 裡再包 component。寫入層由內往外逐層重新編碼。

**同一父字串內的多處編輯必須由後往前**（`span_order`）。改完第一處，其餘 span
全部失效——這不是理論問題，[實測] 三層巢狀確實存在（CLAUDE.md 四節）。
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Iterator

__all__ = [
    "Codec",
    "NodePath",
    "PathStep",
    "decode_step",
    "index_step",
    "key_step",
    "resolve",
    "span_order",
]


class Codec(str, Enum):
    """`decode` 步驟能進入的文件類型。與合約的 enum 綁死。"""

    JSON_COMPONENT = "json_component"
    SNBT = "snbt"
    COMMAND = "command"
    LANG_JSON = "lang_json"


@dataclass(frozen=True)
class PathStep:
    t: str
    name: str | None = None
    i: int | None = None
    codec: Codec | None = None
    arg: str | None = None
    span: tuple[int, int] | None = None

    def to_json(self) -> dict[str, Any]:
        if self.t == "key":
            return {"t": "key", "name": self.name}
        if self.t == "index":
            return {"t": "index", "i": self.i}
        return {
            "t": "decode",
            "codec": self.codec.value if self.codec else None,
            "arg": self.arg,
            "span": list(self.span) if self.span else None,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "PathStep":
        if data["t"] == "key":
            return key_step(data["name"])
        if data["t"] == "index":
            return index_step(data["i"])
        span = data.get("span")
        return decode_step(
            data["codec"],
            arg=data.get("arg"),
            span=tuple(span) if span else None,
        )


def key_step(name: str) -> PathStep:
    return PathStep(t="key", name=name)


def index_step(i: int) -> PathStep:
    return PathStep(t="index", i=i)


def decode_step(
    codec: str | Codec, *, arg: str | None = None, span: tuple[int, int] | None = None
) -> PathStep:
    return PathStep(t="decode", codec=Codec(codec), arg=arg, span=span)


@dataclass(frozen=True)
class NodePath:
    steps: tuple[PathStep, ...]

    def __init__(self, steps: Iterable[PathStep]) -> None:
        object.__setattr__(self, "steps", tuple(steps))

    def __iter__(self) -> Iterator[PathStep]:
        return iter(self.steps)

    def __len__(self) -> int:
        return len(self.steps)

    def to_json(self) -> list[dict[str, Any]]:
        return [step.to_json() for step in self.steps]

    @classmethod
    def from_json(cls, data: list[dict[str, Any]]) -> "NodePath":
        return cls(PathStep.from_json(step) for step in data)

    def child(self, step: PathStep) -> "NodePath":
        return NodePath((*self.steps, step))

    @property
    def last_span(self) -> tuple[int, int] | None:
        """最內層 `decode` 的 span。排序要看的是它，不是最外層那個。"""
        for step in reversed(self.steps):
            if step.t == "decode" and step.span is not None:
                return step.span
        return None


def resolve(root: Any, path: NodePath) -> Any:
    """依路徑走到節點。**`decode` 步驟停在原字串上**——解碼是 codec 的事。"""
    current = root
    for step in path:
        if step.t == "key":
            if step.name not in current:
                raise KeyError(
                    f"走到 {step.name!r} 時找不到這個鍵（路徑：{_describe(path)}）"
                )
            current = current[step.name]
        elif step.t == "index":
            try:
                current = current[step.i]
            except IndexError as exc:
                raise IndexError(
                    f"走到索引 {step.i} 時超出範圍（路徑：{_describe(path)}）"
                ) from exc
        else:
            # decode：以下是另一份文件，走訪到此為止。
            break
    return current


def span_order(paths: Iterable[NodePath]) -> list[NodePath]:
    """把同一父字串裡的編輯排成**由後往前**。

    改完前面那處，後面所有 span 的位移就失效了。這個排序是唯一能讓「位移替換」
    保持正確的順序；不想依賴它就改用結構化重建。
    """
    listed = list(paths)
    return sorted(
        listed,
        key=lambda p: (p.last_span is None, -(p.last_span or (0, 0))[0]),
    )


def _describe(path: NodePath) -> str:
    parts = []
    for step in path:
        if step.t == "key":
            parts.append(str(step.name))
        elif step.t == "index":
            parts.append(f"[{step.i}]")
        else:
            parts.append(f"<{step.codec.value if step.codec else '?'}>")
    return "/".join(parts)
