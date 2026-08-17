# SPDX-License-Identifier: GPL-3.0-or-later
"""`mcmt doctor` — 把 `mcmt.doctor` 的統計印成人看得懂的報告。"""

from mcmt.doctor import WorldSurvey
from mcmt.nbtio.compression import COMPRESSION_NAMES

_REASON_TEXT = {
    "level_wrapper": "chunk 根有 `Level` 包裝層（1.20 之前的容器結構）",
    "legacy_sign_text": "告示牌是 `Text1..Text4`（1.20 之前的告示牌格式）",
    "missing_data_version": "chunk 沒有整數的 `DataVersion`",
}


def format_survey(survey: WorldSurvey) -> str:
    lines = [
        f"世界：{survey.world}",
        f"維度：{len(survey.region_dirs)} 個 region 目錄"
        f"（{'、'.join(survey.region_dirs)}）",
        f"region 檔：{survey.region_files} 個 · chunk：{survey.chunks:,} 個",
        "",
        "DataVersion 直方圖",
    ]
    lines += _histogram(survey.data_versions, survey.chunks, str)
    lines += ["", "壓縮類型"]
    lines += _histogram(
        survey.compression_types,
        survey.chunks,
        lambda t: f"{t} {COMPRESSION_NAMES.get(t, '?')}",
    )
    lines += [
        "",
        f"外部 .mcc chunk：{survey.external_chunks}",
        f"不支援的結構：{sum(survey.unsupported.values())}",
        f"疑似損壞：{len(survey.corrupt)}",
    ]

    for reason, count in survey.unsupported.most_common():
        region, index = survey.unsupported_examples[reason]
        lines.append(
            f"  {reason}：{count} 個 — {_REASON_TEXT.get(reason, '')}"
            f"（例：{region} 的 chunk {index}）"
        )
    for entry in survey.corrupt[:10]:
        where = "" if entry.chunk_index is None else f" chunk {entry.chunk_index}"
        lines.append(f"  {entry.region}{where}：{entry.error} — {entry.detail}")
    if len(survey.corrupt) > 10:
        lines.append(f"  …另有 {len(survey.corrupt) - 10} 筆")

    lines += ["", _verdict(survey)]
    return "\n".join(lines)


def _verdict(survey: WorldSurvey) -> str:
    if survey.supported:
        return "結論：可以處理。"
    return (
        "結論：**拒絕處理這個世界**。理由與 `.mcc` 相同——未測過的寫入路徑比"
        "拒絕處理危險得多。"
    )


def _histogram(counter, total: int, label) -> list[str]:
    if not counter:
        return ["  （無）"]
    width = max(len(label(key)) for key in counter)
    lines = []
    for key, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])):
        share = f"{count / total:6.1%}" if total else "     -"
        lines.append(f"  {label(key):<{width}}  {count:>9,}  {share}")
    return lines
