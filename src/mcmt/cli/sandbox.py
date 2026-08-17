# SPDX-License-Identifier: GPL-3.0-or-later
"""`mcmt sandbox` 的輸出格式。邏輯在 `mcmt.sandbox`。"""

from mcmt.sandbox import ImportResult


def format_import(result: ImportResult) -> str:
    return "\n".join(
        [
            f"已匯入：{result.target}",
            f"  來源：{result.source}",
            f"  檔案：{result.file_count:,} 個",
            f"  來源指紋：{result.world_fingerprint}",
            "",
            "sandbox 是唯一允許寫入的地方。工具永不自動把結果複製回 .minecraft——",
            "那是你的手動決定。",
        ]
    )
