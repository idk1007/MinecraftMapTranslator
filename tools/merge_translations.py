# SPDX-License-Identifier: GPL-3.0-or-later
"""把 LLM 回傳的「識別碼 → 譯文」對照表併回 `mcmt extract` 產出的待翻檔。

用途：大地圖分批交給 LLM 翻譯時，讓 LLM 只吐精簡的
`{"u:sign:xxxx": "譯文", ...}`（省輸出量、避免撞 MAX），再用這支把譯文
逐批寫進 `translations.<lang>.json` 的 `target` 欄位。真正餵給 `mcmt apply`
的檔案自始至終是那份 `translations.<lang>.json`。

用法：

    python tools/merge_translations.py <translations.<lang>.json> <llm_output.json>

分批翻就多跑幾次，每次換一個 llm_output.json，target 會累積填進去。
覆蓋前會先寫一份 `<translations.<lang>.json>.bak`。

llm_output.json 可以是這幾種形狀，都吃：
  {"u:sign:xxxx": "譯文"}                    ← 建議，最精簡
  {"u:sign:xxxx": {"target": "譯文"}}        ← 巢狀也行
  {"entries": {"u:sign:xxxx": {"target": ...}}}  ← 整段 entries 也行
外層若包了 ```json ... ``` 或前後有多餘文字，會盡量擷取中間那段 JSON。
"""

import json
import shutil
import sys
from pathlib import Path
from typing import Any


def _extract_json_blob(text: str) -> str:
    """LLM 常不聽話：把 ```json 圍欄或前後贅語去掉，留中間第一個大括號到最後一個。"""
    stripped = text.strip()
    if stripped.startswith("```"):
        # 去掉開頭 ``` 或 ```json 那一行，以及結尾的 ```
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    first = stripped.find("{")
    last = stripped.rfind("}")
    if first == -1 or last == -1 or last < first:
        raise ValueError("在輸入裡找不到 JSON 物件（沒有成對的大括號）")
    return stripped[first : last + 1]


def _normalise_targets(raw: Any) -> dict[str, str]:
    """把三種可能形狀統一成 {unit_id: target_string}。"""
    if not isinstance(raw, dict):
        raise ValueError("最外層必須是 JSON 物件")
    # {"entries": {...}} → 往裡面看一層
    if "entries" in raw and isinstance(raw["entries"], dict) and len(raw) <= 3:
        raw = raw["entries"]

    out: dict[str, str] = {}
    for uid, value in raw.items():
        if isinstance(value, str):
            out[uid] = value
        elif isinstance(value, dict) and isinstance(value.get("target"), str):
            out[uid] = value["target"]
        else:
            raise ValueError(
                f"{uid} 的值看不懂：預期字串或含 target 的物件，拿到 {type(value).__name__}"
            )
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2

    skeleton_path = Path(argv[1])
    llm_path = Path(argv[2])

    if not skeleton_path.is_file():
        print(f"找不到待翻檔：{skeleton_path}", file=sys.stderr)
        return 1
    if not llm_path.is_file():
        print(f"找不到 LLM 輸出檔：{llm_path}", file=sys.stderr)
        return 1

    skeleton = json.loads(skeleton_path.read_text(encoding="utf-8"))
    if "entries" not in skeleton or not isinstance(skeleton["entries"], dict):
        print(
            f"{skeleton_path} 不像 mcmt 的待翻檔（沒有 entries 物件）。"
            "第一個參數要放 translations.<lang>.json，不要放反了。",
            file=sys.stderr,
        )
        return 1

    try:
        targets = _normalise_targets(json.loads(_extract_json_blob(llm_path.read_text(encoding="utf-8"))))
    except ValueError as exc:
        print(f"讀不懂 {llm_path}：{exc}", file=sys.stderr)
        return 1

    entries = skeleton["entries"]
    filled = 0
    overwritten = 0
    unknown: list[str] = []
    for uid, target in targets.items():
        if uid not in entries:
            unknown.append(uid)
            continue
        existing = entries[uid].get("target", "")
        if existing and existing != target:
            overwritten += 1
        if not existing:
            filled += 1
        entries[uid]["target"] = target

    still_empty = sum(1 for e in entries.values() if not e.get("target"))

    backup = skeleton_path.with_suffix(skeleton_path.suffix + ".bak")
    shutil.copyfile(skeleton_path, backup)
    skeleton_path.write_text(
        json.dumps(skeleton, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"併入 {len(targets)} 筆譯文：")
    print(f"  新填     {filled}")
    if overwritten:
        print(f"  覆蓋既有 {overwritten}（原本就有 target、內容不同）")
    if unknown:
        print(f"  略過     {len(unknown)}（識別碼不在待翻檔裡）")
        for uid in unknown[:10]:
            print(f"             {uid}")
        if len(unknown) > 10:
            print(f"             …還有 {len(unknown) - 10} 個")
    print(f"待翻檔還有 {still_empty} 筆 target 是空的")
    print(f"備份寫到 {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
