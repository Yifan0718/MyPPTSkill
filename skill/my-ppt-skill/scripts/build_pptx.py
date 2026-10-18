#!/usr/bin/env python3
"""Build a new .pptx from a template by selecting slides and replacing text.

The script preserves all layout, fonts, colors, images and animations of the
source template. It only:
  1. Keeps the slides listed in ``selected_slides`` (in that order),
  2. Replaces the text of the runs identified by ``edits``.

USAGE
    python3 build_pptx.py <template.pptx> <edits.json> <output.pptx>
                         [--detail detail.json]   # for slot_id resolution
                         [--strict]               # fail if expected_text mismatch
                         [--dry-run]              # show planned edits, do nothing

EDITS JSON SCHEMA
{
  "template_slug": "simple-business",                 # optional, informational
  "selected_slides": [1, 2, 4, 7, 14, 16],            # 1-indexed in template
  "edits": [
    {
      "slide": 1,                                      # 1-indexed in template
      "slot_id": "title_en",                           # resolved via detail.json
      "new_text": "Annual Review"
    },
    {
      "slide": 1,
      "address": {"shape_id": 46, "paragraph": 1, "run": 0},  # explicit
      "expected_text": "工作计划模板",
      "new_text": "2026 年度工作计划"
    }
  ]
}

ADDRESS FORMS
    {"shape_id": <int>, "paragraph": <int>, "run": <int>}   # exact run
    {"shape_id": <int>, "paragraph": <int>}                  # whole paragraph
                                                              # (run 0 keeps fmt,
                                                              # others cleared)
"""
from __future__ import annotations
import argparse
import copy
import json
import math
import sys
import tempfile
import os
from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.shapes import MSO_SHAPE_TYPE


SLIDE_R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


# ------------------------------------------------------------------
# Slot resolution via detail.json
# ------------------------------------------------------------------
def load_slot_index(detail_path: Path | None) -> dict:
    """Return {(slide_number, slot_id): slot_dict}.

    slot_dict includes address + capacity metadata (max_chars, chars_per_line,
    max_lines, wrap, autofit, font_size_pt, level, role) when present so the
    overflow lint can use them.
    """
    if detail_path is None or not detail_path.exists():
        return {}
    detail = json.loads(detail_path.read_text(encoding="utf-8"))
    index: dict = {}
    for page in detail.get("pages", []):
        slide_number = page["slide_number"]
        for slot in page.get("text_slots", []):
            slot.setdefault("expected_text", slot.get("current_text"))
            index[(slide_number, slot["slot_id"])] = slot
    return index


# ------------------------------------------------------------------
# Overflow lint (text-fits-the-box check)
# ------------------------------------------------------------------
def _visual_width(s: str) -> float:
    w = 0.0
    for c in s:
        if "\u4e00" <= c <= "\u9fff" or "\u3000" <= c <= "\u303f" or "\uff00" <= c <= "\uffef":
            w += 1.0
        elif c == " ":
            w += 0.35
        elif c.isascii():
            w += 0.5
        else:
            w += 0.8
    return w


def check_overflow(new_text: str, meta: dict) -> tuple[bool, str]:
    """Return (fits, message). Uses chars_per_line / max_lines from detail.json.

    'fits' is True when text is expected to fit without shrinking. Autofit
    cannot waive the local font-size floor; it remains a render-review warning.
    """
    if meta.get("capacity_unknown"):
        return True, ""  # geometry unreliable for this box
    cpl = meta.get("chars_per_line")
    max_lines = meta.get("max_lines")
    cap = meta.get("max_chars")   # already includes the calibration tolerance
    if not cpl or not max_lines or not cap:
        return True, ""  # no capacity data → can't lint
    total_vw = _visual_width(new_text.replace("\n", ""))
    # primary test: visual width vs the (tolerance-adjusted) capacity budget
    if total_vw <= cap:
        return True, ""
    # estimate needed lines for a helpful message
    needed = sum(max(1, math.ceil(_visual_width(seg) / cpl))
                 for seg in (new_text.split("\n") or [new_text]))
    sz = meta.get("font_size_pt")
    msg = (f"视觉宽度 {total_vw:.0f} > 容量 {cap} "
           f"(约需 {needed} 行 / 可容 {max_lines} 行, {sz}pt, 每行≈{cpl}字)")
    if meta.get("autofit"):
        return False, "AUTOFIT " + msg + " — 自动缩字可能低于字号下限，必须实际渲染核查"
    return False, msg


# ------------------------------------------------------------------
# Shape lookup (recurses into groups)
# ------------------------------------------------------------------
def find_shape(shapes, shape_id: int):
    for shape in shapes:
        if shape.shape_id == shape_id:
            return shape
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            found = find_shape(shape.shapes, shape_id)
            if found is not None:
                return found
    return None


# ------------------------------------------------------------------
# Text mutation that preserves run-level formatting
# ------------------------------------------------------------------
def apply_edit_to_shape(shape, address: dict, new_text: str, expected: str | None,
                       strict: bool) -> tuple[bool, str]:
    if not shape.has_text_frame:
        return False, f"shape {shape.shape_id} has no text frame"
    tf = shape.text_frame
    pi = address.get("paragraph", 0)
    if type(pi) is not int or pi < 0 or pi >= len(tf.paragraphs):
        return False, f"paragraph {pi} out of range (have {len(tf.paragraphs)})"
    para = tf.paragraphs[pi]
    runs = list(para.runs)
    if not runs:
        return False, f"paragraph {pi} has no runs"

    ri = address.get("run")
    if ri is None:
        current = "".join(r.text for r in runs)
        if expected is not None and current != expected and strict:
            return False, (
                f"expected_text mismatch at paragraph level: "
                f"have {current!r}, expected {expected!r}"
            )
        runs[0].text = new_text
        for r in runs[1:]:
            r.text = ""
        return True, f"replaced paragraph (kept run 0 formatting): {current!r} -> {new_text!r}"

    if type(ri) is not int or ri < 0 or ri >= len(runs):
        return False, f"run {ri} out of range (have {len(runs)})"
    current = runs[ri].text
    if expected is not None and current != expected and strict:
        return False, (
            f"expected_text mismatch: have {current!r}, expected {expected!r}"
        )
    runs[ri].text = new_text
    return True, f"replaced run: {current!r} -> {new_text!r}"


# ------------------------------------------------------------------
# Slide pruning: keep only selected slides, in order
# ------------------------------------------------------------------
def prune_slides(prs, selected_1indexed: list[int]) -> None:
    if len(set(selected_1indexed)) != len(selected_1indexed):
        raise ValueError("selected_slides must not contain duplicates")
    sldIdLst = prs.slides._sldIdLst
    sld_ids = list(sldIdLst)
    total = len(sld_ids)
    keep_idx0 = [i - 1 for i in selected_1indexed]
    for i in keep_idx0:
        if i < 0 or i >= total:
            raise ValueError(f"selected slide {i + 1} out of range (1..{total})")

    # Build new order list of element references.
    new_order = [sld_ids[i] for i in keep_idx0]

    # Remove all entries, then re-append in the new order. Keeping the same
    # element instances preserves their r:id and avoids orphaning relationships.
    for sld in list(sldIdLst):
        sldIdLst.remove(sld)
    for sld in new_order:
        sldIdLst.append(sld)
    # Remove relationships to discarded slides. Otherwise a later save can
    # renumber selected parts onto discarded parts and create duplicate ZIP entries.
    keep_rids = {sld.rId for sld in new_order}
    for sld in sld_ids:
        if sld.rId not in keep_rids:
            prs.part.drop_rel(sld.rId)


# ------------------------------------------------------------------
# Main driver
# ------------------------------------------------------------------
def configure_console() -> None:
    # Logging template text must not abort a valid build on Windows legacy
    # consoles (for example GBK cannot encode an otherwise valid star/emoji).
    # Preserve the caller's selected encoding; escape only unrepresentable log
    # characters. Actual PPTX/JSON text is never transformed here.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='backslashreplace')


def run(args) -> int:
    configure_console()
    if args.template.resolve() == args.output.resolve():
        raise ValueError('Output must not overwrite the source template')
    edits_spec = json.loads(args.edits.read_text(encoding="utf-8"))
    selected = list(edits_spec.get("selected_slides") or [])
    raw_edits = list(edits_spec.get("edits") or [])
    chart_edits = [e for e in raw_edits if "chart_data" in e]
    raw_edits = [e for e in raw_edits if "chart_data" not in e]
    slot_index = load_slot_index(args.detail)

    prs = Presentation(args.template)
    n_slides = len(prs.slides)
    if not selected:
        selected = list(range(1, n_slides + 1))
    if len(set(selected)) != len(selected):
        raise ValueError('selected_slides must not contain duplicates')
    for s in selected:
        if type(s) is not int or s < 1 or s > n_slides:
            print(f"ERROR: selected slide {s} out of range 1..{n_slides}", file=sys.stderr)
            return 2

    for e in raw_edits + chart_edits:
        if type(e.get('slide')) is not int or e['slide'] not in selected:
            raise ValueError('Every edit must target a selected slide using a positive integer')

    # Resolve and group edits by slide_number (in TEMPLATE order, pre-prune)
    planned: list[dict] = []
    for e in raw_edits:
        slide_num = e["slide"]
        meta = None
        if "address" in e:
            addr = dict(e["address"])
            expected = e['expected_text'] if 'expected_text' in e else addr.get('expected_text')
        else:
            slot_id = e.get("slot_id")
            if slot_id is None:
                print(f"ERROR: edit {e} missing both address and slot_id", file=sys.stderr)
                return 2
            key = (slide_num, slot_id)
            if key not in slot_index:
                print(f"ERROR: slot_id {slot_id!r} not found for slide {slide_num} in detail.json",
                      file=sys.stderr)
                return 2
            meta = slot_index[key]
            addr = dict(meta["address"])
            expected = e['expected_text'] if 'expected_text' in e else meta.get('expected_text')
        planned.append({
            "slide": slide_num,
            "address": addr,
            "expected": expected,
            "new_text": e["new_text"],
            "meta": meta,
            "raw": e,
        })

    for e in chart_edits:
        shape = find_shape(prs.slides[e['slide'] - 1].shapes, e['address']['shape_id'])
        if shape is None or not shape.has_chart:
            raise ValueError(f"No native chart at slide {e['slide']}, address {e['address']}")
        chart = shape.chart
        if any(any(kind in type(plot).__name__.upper() for kind in ('XY', 'SCATTER', 'BUBBLE')) for plot in chart.plots):
            raise ValueError("XY/bubble charts require XyChartData/BubbleChartData; category chart_data is unsupported")
        spec = e['chart_data']
        if len(spec['series']) != len(chart.series):
            raise ValueError("Keep the template's series count when replacing category chart data")
        data = CategoryChartData()
        data.categories = spec['categories']
        for series in spec['series']:
            if len(series['values']) != len(spec['categories']):
                raise ValueError("Chart categories and values must have equal lengths")
            data.add_series(series['name'], series['values'])
        chart.replace_data(data)
        if 'chart_title' in e:
            chart.has_title = True
            chart.chart_title.text_frame.text = e['chart_title']
        print(f"OK   slide {e['slide']:>3} chart {shape.shape_id}: replaced native data")

    # Apply edits BEFORE pruning so slide indices match the template
    overflow_issues: list[str] = []
    ellipsis_issues: list[str] = []
    for p in planned:
        slide = prs.slides[p["slide"] - 1]
        shape_id = p["address"].get("shape_id")
        shape = find_shape(slide.shapes, shape_id)
        if shape is None:
            msg = f"slide {p['slide']}: shape_id {shape_id} not found"
            print(f"ERROR: {msg}", file=sys.stderr)
            return 3
        ok, info = apply_edit_to_shape(
            shape, p["address"], p["new_text"], p["expected"], args.strict
        )
        prefix = "OK  " if ok else "ERR "
        print(f"{prefix} slide {p['slide']:>3} shape {shape_id}: {info}")
        if not ok:
            return 4

        # Overflow check — advisory only. max_chars is a soft hint, not a hard
        # limit; we never block or truncate. We only print a gentle note so the
        # author can decide whether to rephrase more concisely.
        if not args.no_lint and p["meta"]:
            fits, omsg = check_overflow(p["new_text"], p["meta"])
            if omsg and not fits:
                slot_id = p["meta"].get("slot_id", "?")
                line = (f"slide {p['slide']:>3} {slot_id}: 可能偏长 {omsg} "
                        f"-> {p['new_text'][:24]!r}")
                overflow_issues.append(line)
                print(f"note {line}", file=sys.stderr)
            elif omsg and fits:  # autofit soft note
                print(f"note  slide {p['slide']:>3}: {omsg}", file=sys.stderr)

        # Catch accidental ellipsis-truncation, which looks worse than a slight
        # overflow. Advisory only.
        stripped = p["new_text"].rstrip()
        if stripped.endswith(("...", "..", "…", "……", "等等", "等。")):
            ellipsis_issues.append(
                f"slide {p['slide']:>3} {(p['meta'] or {}).get('slot_id', '?')}: "
                f"结尾疑似省略号截断 -> {p['new_text'][-16:]!r}")

    if overflow_issues:
        print(f"\n提示：{len(overflow_issues)} 处文字偏长（仅提示，不影响保存）。"
              f"优先改写或调整框宽/布局，不得截断；字号须遵守本地质量规则，过小字号应修复——"
              f"必须修复实际溢出，并渲染验收。", file=sys.stderr)

    if ellipsis_issues:
        print(f"\n⚠️ {len(ellipsis_issues)} 处文字结尾是省略号，很可能是为凑长度而截断"
              f"（这是最差的结果）。请改成完整、精炼的表达：", file=sys.stderr)
        for line in ellipsis_issues:
            print(f"  - {line}", file=sys.stderr)

    prune_slides(prs, selected)
    if args.dry_run:
        print('Validated all edits in memory; no file written.')
        return 0
    from strip_pptx_metadata import transform,findings
    from io import BytesIO
    buffer=BytesIO();prs.save(buffer)
    output_bytes,_=transform(buffer.getvalue(),author=edits_spec.get('author'))
    if findings(output_bytes,author=edits_spec.get('author')):raise ValueError('Metadata validation failed before atomic save')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    fd, temp_name = tempfile.mkstemp(suffix='.pptx', dir=args.output.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        temp_path.write_bytes(output_bytes)
        os.replace(temp_path, args.output)
    finally:
        temp_path.unlink(missing_ok=True)
    note = f"\nSaved {args.output} with {len(selected)} slides and {len(planned)} edits"
    print(note)
    return 0


def main() -> int:
    configure_console()
    ap = argparse.ArgumentParser()
    ap.add_argument("template", type=Path)
    ap.add_argument("edits", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--detail", type=Path, default=None)
    ap.add_argument("--no-lint", action="store_true",
                    help="disable the text-overflow check")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.detail is None:
        # Try sibling detail.json next to the template
        guess = args.template.with_name("detail.json")
        if guess.exists():
            args.detail = guess
            print(f"(auto-detected detail.json: {guess})", file=sys.stderr)

    return run(args)


if __name__ == "__main__":
    sys.exit(main())
