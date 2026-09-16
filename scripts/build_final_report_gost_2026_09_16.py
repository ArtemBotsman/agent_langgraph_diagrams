# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Sequence
from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DELIVERABLES = ROOT / "docs" / "final" / "deliverables"
BUILD = ROOT / ".codex_build" / "report_gost_2026_09_16"
ASSETS = BUILD / "assets"


BLACK = RGBColor(0, 0, 0)
GRAY = "D9D9D9"
LIGHT_GRAY = "F2F2F2"


def fmt(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def pct(value: float, digits: int = 1) -> str:
    return f"{100 * value:.{digits}f}%".replace(".", ",")


def set_repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top=80, start=90, bottom=80, end=90) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for tag, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{tag}"))
        if node is None:
            node = OxmlElement(f"w:{tag}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_repeat_header_footer(section) -> None:
    section.different_first_page_header_footer = True
    footer = section.footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    fld_char_1 = OxmlElement("w:fldChar")
    fld_char_1.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld_char_2 = OxmlElement("w:fldChar")
    fld_char_2.set(qn("w:fldCharType"), "end")
    run._r.append(fld_char_1)
    run._r.append(instr)
    run._r.append(fld_char_2)
    run.font.name = "Times New Roman"
    run.font.size = Pt(12)
    run.font.color.rgb = BLACK


def configure_document(doc: Document) -> None:
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(3.0)
    section.right_margin = Cm(1.5)
    section.header_distance = Cm(1.0)
    section.footer_distance = Cm(1.0)
    set_repeat_header_footer(section)

    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = "Times New Roman"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    normal.font.size = Pt(14)
    normal.font.color.rgb = BLACK
    pf = normal.paragraph_format
    pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf.first_line_indent = Cm(1.25)
    pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    pf.space_after = Pt(0)
    pf.space_before = Pt(0)
    pf.widow_control = True

    for name, size, before, after in (
        ("Title", 16, 0, 12),
        ("Heading 1", 14, 12, 6),
        ("Heading 2", 14, 10, 4),
        ("Heading 3", 14, 8, 3),
    ):
        style = styles[name]
        style.font.name = "Times New Roman"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = BLACK
        style.paragraph_format.first_line_indent = Cm(0)
        style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True

    if "Caption GOST" not in styles:
        cap = styles.add_style("Caption GOST", WD_STYLE_TYPE.PARAGRAPH)
    else:
        cap = styles["Caption GOST"]
    cap.font.name = "Times New Roman"
    cap._element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    cap.font.size = Pt(12)
    cap.font.color.rgb = BLACK
    cap.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.paragraph_format.first_line_indent = Cm(0)
    cap.paragraph_format.space_before = Pt(3)
    cap.paragraph_format.space_after = Pt(6)
    cap.paragraph_format.keep_with_next = True

    if "Table GOST" not in styles:
        tab = styles.add_style("Table GOST", WD_STYLE_TYPE.PARAGRAPH)
    else:
        tab = styles["Table GOST"]
    tab.font.name = "Times New Roman"
    tab._element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    tab.font.size = Pt(10.5)
    tab.font.color.rgb = BLACK
    tab.paragraph_format.first_line_indent = Cm(0)
    tab.paragraph_format.line_spacing = 1.0
    tab.paragraph_format.space_after = Pt(0)
    tab.paragraph_format.space_before = Pt(0)


def add_text(
    doc: Document,
    text: str,
    *,
    bold: bool = False,
    italic: bool = False,
    align=WD_ALIGN_PARAGRAPH.JUSTIFY,
    indent: bool = True,
    keep: bool = False,
) -> None:
    p = doc.add_paragraph()
    p.alignment = align
    p.paragraph_format.first_line_indent = Cm(1.25) if indent else Cm(0)
    p.paragraph_format.keep_with_next = keep
    run = p.add_run(text)
    run.bold = bold
    run.italic = italic
    run.font.name = "Times New Roman"
    run.font.size = Pt(14)
    run.font.color.rgb = BLACK


def add_bullets(doc: Document, items: Iterable[str]) -> None:
    for item in items:
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.left_indent = Cm(1.25)
        p.paragraph_format.first_line_indent = Cm(-0.63)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
        run = p.add_run(item)
        run.font.name = "Times New Roman"
        run.font.size = Pt(14)
        run.font.color.rgb = BLACK


def add_numbered(doc: Document, items: Iterable[str]) -> None:
    for index, item in enumerate(items, 1):
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(1.25)
        p.paragraph_format.first_line_indent = Cm(-0.63)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
        run = p.add_run(f"{index}) {item}")
        run.font.name = "Times New Roman"
        run.font.size = Pt(14)
        run.font.color.rgb = BLACK


def add_table(
    doc: Document,
    headers: Sequence[str],
    rows: Sequence[Sequence[object]],
    *,
    widths: Sequence[float] | None = None,
) -> None:
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    header = table.rows[0]
    set_repeat_table_header(header)
    for col, value in enumerate(headers):
        cell = header.cells[col]
        set_cell_shading(cell, GRAY)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        set_cell_margins(cell)
        cell.text = str(value)
        for p in cell.paragraphs:
            p.style = "Table GOST"
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in p.runs:
                run.bold = True
                run.font.color.rgb = BLACK
        if widths:
            cell.width = Cm(widths[col])
    for row_idx, values in enumerate(rows, 1):
        cells = table.add_row().cells
        for col, value in enumerate(values):
            cell = cells[col]
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            set_cell_margins(cell)
            if row_idx % 2 == 0:
                set_cell_shading(cell, LIGHT_GRAY)
            cell.text = str(value)
            for p in cell.paragraphs:
                p.style = "Table GOST"
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                for run in p.runs:
                    run.font.color.rgb = BLACK
            if widths:
                cell.width = Cm(widths[col])
    doc.add_paragraph().paragraph_format.space_after = Pt(1)


def add_table_caption(doc: Document, number: int, caption: str) -> None:
    p = doc.add_paragraph(style="Caption GOST")
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.add_run(f"Таблица {number} — {caption}")


def add_figure(doc: Document, image_path: Path, number: int, caption: str, width_cm=16.0) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Cm(0)
    p.paragraph_format.keep_with_next = True
    p.add_run().add_picture(str(image_path), width=Cm(width_cm))
    cap = doc.add_paragraph(style="Caption GOST")
    cap.add_run(f"Рисунок {number} — {caption}")


def add_page_break(doc: Document) -> None:
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


FONT = Path("/System/Library/Fonts/Supplemental/Times New Roman.ttf")
FONT_BOLD = Path("/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf")


def font(size: int, bold: bool = False):
    return ImageFont.truetype(str(FONT_BOLD if bold else FONT), size)


def centered(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, fnt, *, fill="black") -> None:
    box = draw.multiline_textbbox((0, 0), text, font=fnt, align="center", spacing=4)
    draw.multiline_text((xy[0] - (box[2]-box[0])/2, xy[1] - (box[3]-box[1])/2), text, font=fnt, fill=fill, align="center", spacing=4)


def hatched_bar(draw, box, *, fill="white", hatch=False):
    x0, y0, x1, y1 = map(int, box)
    draw.rectangle((x0, y0, x1, y1), fill=fill, outline="black", width=2)
    if hatch:
        for x in range(x0 - (y1-y0), x1 + (y1-y0), 14):
            draw.line((x, y1, x + (y1-y0), y0), fill="#777777", width=1)


def build_architecture_figure(path: Path) -> None:
    im = Image.new("RGB", (1600, 2200), "white")
    d = ImageDraw.Draw(im)
    centered(d, (800, 90), "Общая архитектура решения", font(52, True))
    boxes = [
        (180, 220, 1420, 420, "Вход: SpecificationReq\nзадача, цель, описание, ФТ и НФТ"),
        (180, 530, 1420, 730, "Нормализация требований\nFR-001… / NFR-001… / атомизация"),
        (180, 840, 1420, 1110, "Агент вариантов использования\nгенерация → проверка схемы → формальные проверки\n→ критика → ограниченное исправление"),
        (180, 1220, 1420, 1520, "Агент диаграмм деятельности — для каждого принятого UC\nгенерация → проверка схемы → формальные проверки\n→ критика → ограниченное исправление → Mermaid"),
        (180, 1630, 1420, 1840, "Сквозная проверка и упаковка\nреестр трассировки · валидаторы · модуль оценки"),
        (180, 1950, 1420, 2140, "Выход: варианты использования · истории · Activity\nMermaid · трассировка · отчёт качества"),
    ]
    for x0, y0, x1, y1, text in boxes:
        d.rounded_rectangle((x0, y0, x1, y1), radius=26, fill="#F2F2F2", outline="black", width=3)
        centered(d, ((x0+x1)/2, (y0+y1)/2), text, font(34, True if y0 in (840,1220) else False))
    for upper, lower in zip(boxes, boxes[1:], strict=False):
        x = 800
        y0 = upper[3] + 10
        y1 = lower[1] - 15
        d.line((x, y0, x, y1), fill="black", width=4)
        d.polygon(((x-14, y1-24), (x+14, y1-24), (x, y1)), fill="black")
    im.save(path)


def build_bar_chart(path: Path, title: str, labels: Sequence[str], series: Sequence[tuple[str, Sequence[float], str, bool]], *, y_label: str, max_value: float = 1.1, value_fmt="float") -> None:
    w, h = 1900, 1050
    im = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(im)
    centered(d, (w/2, 70), title, font(48, True))
    left, top, right, bottom = 170, 210, 1830, 850
    d.line((left, top, left, bottom), fill="black", width=3)
    d.line((left, bottom, right, bottom), fill="black", width=3)
    for i in range(6):
        val = max_value * i / 5
        y = bottom - (bottom-top)*i/5
        d.line((left, y, right, y), fill="#D9D9D9", width=2)
        txt = f"{val:.1f}" if max_value <= 2 else f"{val:.0f}"
        d.text((left-80, y-14), txt, font=font(25), fill="black")
    d.text((20, 490), y_label, font=font(28), fill="black")
    group_w = (right-left)/len(labels)
    nseries = len(series)
    bar_w = min(95, group_w/(nseries+1))
    legend_x = left + 20
    for si, (name, values, fill, hatch) in enumerate(series):
        lx = legend_x + si*460
        hatched_bar(d, (lx, 150, lx+55, 190), fill=fill, hatch=hatch)
        d.text((lx+70, 153), name, font=font(28), fill="black")
        for i, value in enumerate(values):
            cx = left + group_w*(i+0.5) + (si-(nseries-1)/2)*(bar_w+8)
            y = bottom - (bottom-top)*(value/max_value)
            hatched_bar(d, (cx-bar_w/2, y, cx+bar_w/2, bottom), fill=fill, hatch=hatch)
            if value_fmt == "fraction5":
                label = f"{round(value*5):d}/5"
            elif value_fmt == "fraction3":
                label = f"{round(value*3):d}/3"
            elif value_fmt == "int":
                label = f"{round(value):d}"
            else:
                label = f"{value:.2f}"
            centered(d, (cx, y-25), label, font(23, True))
    for i, label in enumerate(labels):
        centered(d, (left+group_w*(i+0.5), bottom+75), label, font(25))
    im.save(path)


def build_dev20_figure(path: Path) -> None:
    build_bar_chart(path, "Один вызов LLM и полный граф на DEV20 × 3",
        ["Акторы", "Варианты\nиспользования", "Этапы", "Ветвления", "Трассировка", "E2E"],
        [("Один вызов LLM", [0.7099206,0.8466667,0.2490361,0.3144444,0.835,0.0333333], "white", True),
         ("Полный граф", [0.8139683,0.9703896,0.2705340,0.4517857,0.9630379,1.0], "#666666", False)],
        y_label="Значение, 0–1")


def build_trace_counts_figure(path: Path) -> None:
    build_bar_chart(path, "Связи ФТ → варианты использования: микроагрегация",
        ["Верные\nсвязи (TP)", "Лишние\nсвязи (FP)", "Пропущенные\nсвязи (FN)"],
        [("Один вызов LLM", [250,6,65], "white", True), ("Полный граф", [302,14,13], "#666666", False)],
        y_label="Число связей", max_value=330, value_fmt="int")


def build_scaling_figure(path: Path) -> None:
    build_bar_chart(path, "Устойчивость при росте числа функциональных требований",
        ["6–10 ФТ", "12–19 ФТ", "24–48 ФТ", "54–74 ФТ"],
        [("Один вызов LLM", [1.0,0.8,0.0,0.0], "white", True), ("Полный граф", [1.0,1.0,1.0,0.8], "#666666", False)],
        y_label="Доля проектов E2E", value_fmt="fraction5")


def build_critic_figure(path: Path) -> None:
    build_bar_chart(path, "Постоянный критик: DEV20 × 3",
        ["Акторы", "Варианты\nиспользования", "Этапы", "Ветвления", "Трассировка", "E2E"],
        [("Без критика", [0.812143,0.988485,0.270434,0.417817,0.965674,1.0], "white", True),
         ("Полный граф", [0.813968,0.970390,0.270534,0.451786,0.963038,1.0], "#666666", False)],
        y_label="Среднее, 0–1")


def build_cross_model_figure(path: Path) -> None:
    build_bar_chart(path, "Переносимость на трёх моделях: один простой проект",
        ["DeepSeek", "GPT-5.5", "Claude Opus 5"],
        [("Один вызов LLM", [0.0,1.0,1.0], "white", True), ("Полный граф", [1.0,1.0,1.0], "#666666", False)],
        y_label="Доля E2E, n = 3", value_fmt="fraction3")


def build_figures() -> dict[str, Path]:
    ASSETS.mkdir(parents=True, exist_ok=True)
    paths = {
        "architecture": ASSETS / "01_architecture_bw.png",
        "dev20": ASSETS / "02_dev20_metrics_bw.png",
        "trace_counts": ASSETS / "03_trace_counts_bw.png",
        "scaling": ASSETS / "04_scaling_e2e_bw.png",
        "critic": ASSETS / "05_critic_bw.png",
        "models": ASSETS / "06_cross_model_bw.png",
    }
    build_architecture_figure(paths["architecture"])
    build_dev20_figure(paths["dev20"])
    build_trace_counts_figure(paths["trace_counts"])
    build_scaling_figure(paths["scaling"])
    build_critic_figure(paths["critic"])
    build_cross_model_figure(paths["models"])
    return paths


def add_title_page(doc: Document) -> None:
    for _ in range(2):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Cm(0)
    r = p.add_run("УНИВЕРСИТЕТ ИТМО")
    r.bold = True
    r.font.name = "Times New Roman"
    r.font.size = Pt(16)
    r.font.color.rgb = BLACK
    for _ in range(4):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Cm(0)
    r = p.add_run("ТЕХНИЧЕСКИЙ ОТЧЁТ")
    r.bold = True
    r.font.name = "Times New Roman"
    r.font.size = Pt(16)
    r.font.color.rgb = BLACK
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Cm(0)
    p.paragraph_format.space_before = Pt(16)
    r = p.add_run("Агентная генерация вариантов использования и диаграмм деятельности\nпо функциональным и нефункциональным требованиям")
    r.bold = True
    r.font.name = "Times New Roman"
    r.font.size = Pt(16)
    r.font.color.rgb = BLACK
    for _ in range(6):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.paragraph_format.first_line_indent = Cm(0)
    r = p.add_run("Исполнитель: Боцман Артём\nВерсия отчёта: 13 сентября 2026 г.")
    r.font.name = "Times New Roman"
    r.font.size = Pt(14)
    r.font.color.rgb = BLACK
    for _ in range(6):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Cm(0)
    r = p.add_run("Санкт-Петербург\n2026")
    r.font.name = "Times New Roman"
    r.font.size = Pt(14)
    r.font.color.rgb = BLACK
    add_page_break(doc)


TOC_ENTRIES = [
    "РЕФЕРАТ",
    "ПЕРЕЧЕНЬ СОКРАЩЕНИЙ И ОБОЗНАЧЕНИЙ",
    "1 Постановка задачи",
    "2 Обзор подходов и аналогов",
    "3 Входные данные и типизированные модели",
    "4 Архитектура и реализация",
    "5 Методика экспериментальной оценки",
    "6 Результаты экспериментов",
    "7 Обсуждение результатов",
    "8 Ограничения и угрозы достоверности",
    "9 Воспроизводимость и развёртывание",
    "ЗАКЛЮЧЕНИЕ",
    "СПИСОК ИСПОЛЬЗОВАННЫХ ИСТОЧНИКОВ",
    "ПРИЛОЖЕНИЕ А. Карта файлов воспроизведения",
]


def add_contents(doc: Document, toc_pages: dict[str, int] | None) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Cm(0)
    r = p.add_run("СОДЕРЖАНИЕ")
    r.bold = True
    r.font.name = "Times New Roman"
    r.font.size = Pt(14)
    r.font.color.rgb = BLACK
    for entry in TOC_ENTRIES:
        p = doc.add_paragraph()
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.line_spacing = 1.15
        p.paragraph_format.space_after = Pt(3)
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        tab_stops = p.paragraph_format.tab_stops
        tab_stops.add_tab_stop(Cm(16.0))
        page = str((toc_pages or {}).get(entry, "—"))
        run = p.add_run(f"{entry}\t{page}")
        run.font.name = "Times New Roman"
        run.font.size = Pt(12)
        run.font.color.rgb = BLACK
    add_page_break(doc)


def add_major_heading(doc: Document, text: str) -> None:
    p = doc.add_paragraph(style="Heading 1")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run(text)


def build_report(output: Path, toc_pages: dict[str, int] | None = None) -> None:
    figs = build_figures()
    doc = Document()
    configure_document(doc)
    cp = doc.core_properties
    cp.title = "Технический отчёт: агентная генерация вариантов использования и диаграмм деятельности"
    cp.author = "Боцман Артём"
    cp.subject = "LangGraph, варианты использования, диаграммы деятельности, трассировка"
    cp.keywords = "LangGraph, LLM, Use Case, Activity Diagram, Mermaid, трассировка"
    cp.comments = "Редакция 16.09.2026. Оформление приближено к ГОСТ 7.32-2017."

    add_title_page(doc)
    add_contents(doc, toc_pages)

    add_major_heading(doc, "РЕФЕРАТ")
    add_text(
        doc,
        "Отчёт содержит описание и экспериментальную проверку программной системы, которая преобразует функциональные и нефункциональные требования к приложению в структурированные варианты использования, пользовательские и системные истории, типизированные диаграммы деятельности, Mermaid-представления и двусторонний реестр трассировки. Система располагается после аналитического этапа и до кодогенерации: пользователь получает проверяемое описание поведения до запуска более дорогого этапа создания кода."
    )
    add_text(
        doc,
        "Решение реализовано на Python и LangGraph как два специализированных агентных подграфа и корневой оркестратор. Большая языковая модель интерпретирует смысл требований; детерминированный код назначает идентификаторы, проверяет схемы, целостность ссылок, графовые инварианты и ограничивает число исправлений. Итоговые изображения строятся Mermaid-рендерером по принятой типизированной модели; языковая модель не рисует изображение непосредственно."
    )
    add_text(
        doc,
        "На контролируемом наборе DEV20 выполнено по три независимых повтора одиночного вызова LLM и полного графа. Полный граф прошёл сквозную проверку в 60 из 60 запусков, одиночный вызов — в 2 из 60. Средняя по проектам F-мера трассировки составила 0,963 против 0,835. На отдельном наборе из 20 проектов руководителя размером от 6 до 74 функциональных требований полный граф завершил 19 из 20 проектов, одиночный вызов — 9 из 20; парная разность равна 0,50, 95%-й доверительный интервал [0,30; 0,70], p = 0,001953. Цена надёжности — увеличение медианного времени с 16,1 до 56,3 с и среднего расхода с 10,6 до 62,0 тыс. токенов на запуск DEV20."
    )
    add_text(doc, "Ключевые слова: требования, варианты использования, диаграммы деятельности, агентная система, LangGraph, трассировка, Mermaid, валидация, воспроизводимость.", italic=True)
    add_page_break(doc)

    add_major_heading(doc, "ПЕРЕЧЕНЬ СОКРАЩЕНИЙ И ОБОЗНАЧЕНИЙ")
    add_table(doc, ["Обозначение", "Расшифровка"], [
        ["ФТ", "функциональное требование"],
        ["НФТ", "нефункциональное требование"],
        ["LLM", "большая языковая модель"],
        ["UC", "вариант использования"],
        ["E2E", "сквозная успешность всего комплекта артефактов"],
        ["F1", "F-мера, гармоническое среднее точности и полноты"],
        ["DEV20", "открытая часть тестового набора из 20 проектов"],
        ["Gold", "зафиксированная эталонная разметка ожидаемых элементов"],
        ["TraceManifest", "машиночитаемый реестр прямых и обратных связей"],
    ], widths=[3.2, 12.0])
    add_page_break(doc)

    add_major_heading(doc, "1 Постановка задачи")
    doc.add_paragraph("1.1 Проблема и место решения в жизненном цикле", style="Heading 2")
    add_text(doc, "Исходные требования описывают функции и ограничения приложения естественным языком. Между ними и программным кодом отсутствует проверяемый поведенческий слой: границы процессов, участники, основной ход, альтернативы, ошибки и происхождение элементов часто остаются неявными. Если неоднозначность обнаруживается только после кодогенерации, исправление затрагивает уже созданный код, тесты и документацию.")
    add_text(doc, "Разработанная система располагается после аналитика и до кодирующего агента. Она уменьшает неоднозначность не за счёт общей переформулировки текста, а за счёт явного представления акторов, шагов, ожидаемых результатов, ветвлений и связей с исходными требованиями. Пользователь может проверить сценарии и диаграммы до кодогенерации и локализовать замечание до конкретного требования.")
    doc.add_paragraph("1.2 Почему недостаточно детерминированных средств", style="Heading 2")
    add_text(doc, "Pyreverse, GitDiagram, DeepWiki и другие средства обратного анализа получают структуру из существующего кода или репозитория. Они полезны после реализации, но не решают задачу до кода: не выводят из требований бизнес-цели, границы вариантов использования, альтернативные и ошибочные сценарии. Mermaid CLI и Structurizr DSL визуализируют уже заданное описание, но сами не интерпретируют требования.")
    add_text(doc, "LLM необходима для смысловой декомпозиции естественного языка. Однако вероятностный ответ без контроля может содержать пропуски, лишние элементы и некорректные ссылки. Поэтому применяется гибридный подход: LLM предлагает содержание, а типизированные модели, валидаторы и ограниченные циклы исправления обеспечивают контролируемость.")
    doc.add_paragraph("1.3 Цель и задачи", style="Heading 2")
    add_text(doc, "Цель работы — разработать и экспериментально проверить воспроизводимый агентный конвейер, который до кодогенерации формирует из ФТ и НФТ полный, машинно-проверяемый и трассируемый комплект вариантов использования и диаграмм деятельности.", bold=True)
    add_numbered(doc, [
        "определить типизированные модели входных требований, вариантов использования, сценарных шагов, диаграмм деятельности и связей трассировки;",
        "реализовать два специализированных графа и корневой оркестратор с ограниченными циклами проверки и исправления;",
        "реализовать формальные проверки, семантическую критику, ограниченное исправление и детерминированный рендеринг Mermaid;",
        "подготовить тестовые наборы, эталонную разметку, валидаторы и метрики качества для входов разного размера;",
        "сравнить полный граф с одиночным вызовом той же LLM по качеству, сквозной успешности, трассировке, времени и стоимости."
    ])

    add_major_heading(doc, "2 Обзор подходов и аналогов")
    add_text(doc, "Прямого количественного аналога с тем же входом и полным набором выходов не найдено. Поэтому аналоги разделены по фактическому назначению, а прямым экспериментальным базовым вариантом выбран одиночный вызов той же LLM с теми же входом, схемой результата и модулем оценки.")
    add_table_caption(doc, 1, "Сопоставление существующих подходов")
    add_table(doc, ["Подход", "Вход", "Результат", "Ограничение относительно задачи"], [
        ["Pyreverse", "Python-код", "структурные UML-диаграммы", "код уже должен существовать; поведение из требований не выводится"],
        ["GitDiagram", "репозиторий", "обзор структуры репозитория", "работает после реализации и не формирует варианты использования"],
        ["DeepWiki / DeepWiki-Open", "репозиторий", "документация и диаграммы", "переносит LLM-вызовы в другой сервис; входом остаётся код"],
        ["Mermaid CLI", "готовый Mermaid-код", "SVG/PNG", "рендерер, а не средство анализа требований"],
        ["Structurizr DSL", "архитектурная модель", "архитектурные представления", "требует заранее заданной модели"],
        ["Одиночный запрос к LLM", "SpecificationReq", "весь комплект за один ответ", "нет промежуточной локализации ошибок и ограниченного восстановления"],
        ["NOMAD", "естественно-языковые требования", "диаграммы классов", "подтверждает принцип специализации агентов, но решает структурную, а не поведенческую задачу"],
        ["Разработанное решение", "SpecificationReq", "UC, истории, Activity, Mermaid, трассировка, отчёт", "более высокая цена; качество зависит от модели и эталонной разметки"],
    ], widths=[3.0, 3.1, 4.1, 5.1])
    add_text(doc, "Ferrari и соавторы показали, что при генерации UML из требований встречаются пропуски, неверные акторы, структурные дефекты и неполная трассировка. NOMAD демонстрирует полезность разделения задач между специализированными агентами, но отмечает неоднозначный эффект постоянной проверки. Query2Diagram использует принцип «типизированный граф — затем рендеринг» и отделяет структурные дефекты от смысловой релевантности. Эти наблюдения непосредственно повлияли на архитектуру и методику оценки данной работы.")

    add_major_heading(doc, "3 Входные данные и типизированные модели")
    doc.add_paragraph("3.1 Входной контракт", style="Heading 2")
    add_text(doc, "Внешний контракт SpecificationReq содержит шесть полей: project_task, project_name, project_goal, project_description, functional_requirements и non_functional_requirements. Первые четыре поля являются непустыми строками; ФТ и НФТ задаются списками строк. После приёма входа детерминированная функция назначает стабильные идентификаторы FR-001, FR-002, … и NFR-001, NFR-002, …. Явные перечисления и части, разделённые точкой с запятой, могут быть атомизированы в FRA-…; союзы автоматически не расщепляются, чтобы не изменить бизнес-смысл.")
    add_table_caption(doc, 2, "Основные типизированные сущности")
    add_table(doc, ["Сущность", "Ключевые поля", "Назначение"], [
        ["SpecificationRequest", "задача, название, цель, описание, ФТ, НФТ", "нормализованный вход со стабильными ID"],
        ["UseCase", "актор, цель, триггер, предусловия, сценарии, постусловия", "граница бизнес-процесса"],
        ["ScenarioStep", "ID, порядок, actor_id, действие, ожидаемый результат, source_fr_ids", "атомарный проверяемый шаг"],
        ["ActivityDiagram", "дорожки, вершины, рёбра, условия, use_case_id", "типизированная модель поведения"],
        ["TraceLink", "источник, назначение, тип связи, происхождение", "явная связь между уровнями"],
        ["ValidationReport", "статус и список блокирующих/неблокирующих проблем", "решение о принятии или исправлении"],
    ], widths=[3.1, 7.5, 5.0])
    doc.add_paragraph("3.2 Структура варианта использования", style="Heading 2")
    add_text(doc, "Вариант использования хранится не как произвольный абзац. Обязательными являются имя, цель, основной актор, триггер, основной сценарий и хотя бы одна ссылка на ФТ. Дополнительно задаются вторичные акторы, предусловия, успешные и неуспешные постусловия, альтернативные и исключительные сценарии, пользовательские и системные истории, отсутствующая информация и неподтверждённые предположения.")
    add_text(doc, "Каждый сценарный шаг содержит исполнителя, действие, ожидаемый результат и ссылки на исходные ФТ. Пользовательская история формулирует ценность для роли, а системная история — внутреннюю ответственность системы. Если actor_id отсутствует, действие относится к самой проектируемой системе, а не к оркестратору или LLM.")
    doc.add_paragraph("3.3 Структура диаграммы деятельности", style="Heading 2")
    add_text(doc, "Для каждого принятого варианта использования создаётся одна диаграмма деятельности. Она содержит дорожки участников, вершины начала, действия, решения, объединения и завершения, а также ориентированные рёбра с условиями. Поле use_case_id связывает диаграмму с вариантом использования; related_step_ids у вершины или ребра указывает конкретные шаги сценария, из которых элемент получен. Система не генерирует множество картинок для выбора лучшей: одна типизированная модель последовательно проверяется и при необходимости исправляется.")

    add_major_heading(doc, "4 Архитектура и реализация")
    add_figure(doc, figs["architecture"], 1, "Общая архитектура агентного конвейера", width_cm=14.7)
    doc.add_paragraph("4.1 Состав графов", style="Heading 2")
    add_text(doc, "Исполняемых содержательных агентов два: агент вариантов использования и агент диаграмм деятельности. Корневой граф является оркестратором: он нормализует вход, запускает первый подграф, последовательно запускает второй подграф для каждого принятого UC, выполняет сквозную проверку, модуль оценки и упаковку результата. Генератор, критик и редактор являются внутренними LLM-ролями, а не отдельными агентами.")
    add_table_caption(doc, 3, "Статический состав графов")
    add_table(doc, ["Граф", "Рабочие вершины", "Логические переходы", "Функция"], [
        ["Корневой оркестратор", "6", "7", "порядок, состояние, цикл по UC, итоговая проверка"],
        ["Агент вариантов использования", "9", "13", "генерация, схема, формальные проверки, критика, решение, исправление"],
        ["Агент диаграмм деятельности", "10", "14", "генерация Activity, проверки, критика, исправление, Mermaid"],
        ["Итого", "25", "34", "три связанных графа"],
    ], widths=[4.1, 3.0, 3.3, 5.4])
    doc.add_paragraph("4.2 Проверка, критика и ограниченное исправление", style="Heading 2")
    add_text(doc, "Проверка схемы гарантирует типы, обязательные поля и форматы идентификаторов. Детерминированные валидаторы проверяют покрытие требований, уникальность, ссылочную целостность, начало и конец диаграммы, достижимость, допустимые переходы, ветвления и принадлежность элементов существующим шагам. При блокирующей формальной ошибке дорогой критик может быть пропущен: системе уже известен точный код дефекта и затронутые ID.")
    add_text(doc, "Семантический критик получает типизированный результат и отчёты валидаторов, оценивает содержательные пропуски и возвращает структурированный вердикт. Редактор получает не общий запрос «сделать лучше», а список проблем и ID элементов. По умолчанию разрешено не более двух исправлений. Ограничение предотвращает бесконечный цикл, фиксирует верхнюю границу стоимости и переводит неустранённый дефект в явный контролируемый отказ. Значение настраиваемо от 0 до 10; два повтора выбраны как инженерный компромисс и отдельно исследуются.")
    doc.add_paragraph("4.3 Трассировка и рендеринг", style="Heading 2")
    add_text(doc, "TraceManifest хранит прямые и обратные связи по цепочке ФТ → вариант использования → сценарный шаг → вершина или ребро диаграммы. Ссылка на несуществующий конечный элемент не является допустимой: материализация и валидаторы должны либо создать согласованный элемент, либо удалить/отклонить висячую ссылку. Благодаря этому по замечанию к диаграмме можно найти исходное требование, а по требованию — все связанные сценарии и элементы.")
    add_text(doc, "После принятия Activity-модели обычная функция создаёт Mermaid-текст. Строка flowchart TD задаёт направленный сверху вниз граф; затем объявляются узлы, дорожки, переходы и подписи условий. Mermaid CLI преобразует текст в SVG/PNG. Рендерер не принимает решений о бизнес-смысле и не заменяет валидаторы.")
    doc.add_paragraph("4.4 Хранение и обработка ошибок", style="Heading 2")
    add_text(doc, "Промежуточное состояние может сохраняться в SQLite с thread_id. Повторные запросы к провайдеру ограничены по числу вызовов, токенам и оценочной стоимости; для временных кодов 408, 409, 425, 429 и 5xx применяется повтор с задержкой. Секреты читаются из локальных .env-файлов, которые исключены из Git. В публичный комплект записываются безопасная конфигурация, обезличенная телеметрия и итоговые артефакты.")

    add_major_heading(doc, "5 Методика экспериментальной оценки")
    doc.add_paragraph("5.1 Тестовые наборы", style="Heading 2")
    add_table_caption(doc, 4, "Использованные тестовые наборы")
    add_table(doc, ["Набор", "Состав", "Назначение", "Статус эталона"], [
        ["Контролируемый benchmark", "30 проектов: DEV20 и sealed hidden10; 8 простых, 13 средних, 9 сложных; 13 RU и 17 EN", "качество содержания, трассировка, повторяемость", "авторская техническая Gold-разметка; hidden не использован"],
        ["Набор руководителя", "20 проектов, четыре группы по 5; 6–74 ФТ", "масштабирование, E2E, время, стоимость", "Gold-кандидат заморожен, ожидает двух независимых экспертов"],
    ], widths=[3.0, 6.0, 3.8, 3.8])
    add_text(doc, "Контролируемые проекты синтетически сформированы из типовых бизнес-процессов. Для каждого заранее заданы ожидаемые акторы, варианты использования, ключевые этапы, ветвления, связи ФТ → UC, допустимые синонимы и запрещённые предположения. Набор руководителя получен отдельно и не является продолжением этих 30 кейсов; для него подготовлена собственная Gold-разметка-кандидат.")
    doc.add_paragraph("5.2 Сравниваемые режимы", style="Heading 2")
    add_text(doc, "Основное сравнение проводится между одиночным вызовом LLM и полным графом. Одинаковы вход, версия модели, провайдер, целевая JSON Schema и модуль оценки; различается только организация процесса. Дополнительно исследованы режимы без критика и без исправления, а также переносимость на DeepSeek, GPT-5.5 и Claude Opus 5.")
    doc.add_paragraph("5.3 Метрики", style="Heading 2")
    add_text(doc, "Для сопоставления с Gold используются точность P = TP/(TP+FP), полнота R = TP/(TP+FN) и F1 = 2PR/(P+R). TP — подтверждённый элемент, FP — лишний неподтверждённый элемент, FN — пропущенный ожидаемый элемент. Эквивалентные названия учитываются по заранее зафиксированным правилам, а не после просмотра результата.")
    add_table_caption(doc, 5, "Метрики и их практический смысл")
    add_table(doc, ["Метрика", "Объект", "Интерпретация"], [
        ["Actor F1", "акторы", "правильно ли определены участники процесса"],
        ["UC F1", "варианты использования", "правильно ли выделены границы процессов"],
        ["Milestone F1", "основные шаги", "сохранены ли обязательные этапы"],
        ["Branch F1", "альтернативные/ошибочные пути", "сохранены ли бизнес-условия и исключения"],
        ["Trace F1", "связи ФТ → UC", "можно ли доказать происхождение результата"],
        ["FR/Activity coverage", "требования и элементы Activity", "ничего ли не потеряно между уровнями"],
        ["Activity structural validity", "структура диаграммы", "пройдены ли детерминированные инварианты"],
        ["E2E success", "весь комплект", "можно ли принять результат без ручного ремонта формата и ссылок"],
        ["Время, токены, стоимость", "журнал LLM-вызовов", "цена получения принимаемого результата"],
    ], widths=[3.8, 4.8, 7.0])
    doc.add_paragraph("5.4 Статистический протокол", style="Heading 2")
    add_text(doc, "На DEV20 выполнено по три независимых повтора на проект и режим. Для средних значений по проектам использован кластерный bootstrap с 95%-м доверительным интервалом; единицей анализа является проект, а повторы усредняются внутри проекта. Для парной бинарной E2E-метрики применён точный двусторонний критерий Мак-Немара/биномиальный критерий, множественные проверки DEV20 скорректированы методом Холма. На размерном наборе выполнен один запуск на проект, поэтому доверительный интервал отражает различия между проектами, но не стохастическую повторяемость.")

    add_major_heading(doc, "6 Результаты экспериментов")
    doc.add_paragraph("6.1 Основное сравнение на DEV20", style="Heading 2")
    add_figure(doc, figs["dev20"], 2, "Сравнение одиночного вызова и полного графа на DEV20 × 3", width_cm=16.0)
    add_table_caption(doc, 6, "Макросредние значения по проектам и 95%-е доверительные интервалы")
    add_table(doc, ["Метрика", "Один вызов LLM", "Полный граф", "Разность"], [
        ["Actor F1", "0,710 [0,607; 0,810]", "0,814 [0,744; 0,880]", "+0,104"],
        ["UC F1", "0,847 [0,747; 0,933]", "0,970 [0,922; 1,000]", "+0,124"],
        ["Milestone F1", "0,249 [0,199; 0,297]", "0,271 [0,214; 0,324]", "+0,021"],
        ["Branch F1", "0,314 [0,188; 0,456]", "0,452 [0,304; 0,606]", "+0,137"],
        ["Trace F1", "0,835 [0,733; 0,925]", "0,963 [0,929; 0,990]", "+0,128"],
        ["E2E success", "2/60 (0,033)", "60/60 (1,000)", "+0,967"],
    ], widths=[3.7, 4.5, 4.5, 2.4])
    add_text(doc, "Наиболее сильный подтверждённый результат — рост сквозной принимаемости с 2/60 до 60/60: +96,7 процентного пункта, 95%-й ДИ [+91,7; +100,0], p = 5,72×10⁻⁶ после поправки Холма. Прирост Milestone F1 мал, поэтому утверждать универсальное улучшение каждой содержательной характеристики нельзя. Подтверждённый вывод состоит в повышении формальной надёжности, границ процессов и трассировки.")

    doc.add_paragraph("6.2 Связи требований с вариантами использования", style="Heading 2")
    add_figure(doc, figs["trace_counts"], 3, "Верные, лишние и пропущенные связи ФТ → UC", width_cm=15.2)
    add_table_caption(doc, 7, "Микроагрегация связей ФТ → UC на DEV20")
    add_table(doc, ["Режим", "Ожидалось", "TP", "FP", "FN", "Precision", "Recall", "F1"], [
        ["Один вызов", "315", "250", "6", "65", "0,977", "0,794", "0,876"],
        ["Полный граф", "315", "302", "14", "13", "0,956", "0,959", "0,957"],
    ], widths=[2.7, 1.9, 1.4, 1.4, 1.4, 2.0, 2.0, 1.7])
    add_text(doc, "Полный граф нашёл на 52 корректные связи больше и сократил пропуски с 65 до 13. Одновременно число лишних связей увеличилось с 6 до 14, поэтому Precision немного снизилась. Итоговая микро-F1 выросла с 0,876 до 0,957. Макро Trace F1 в таблице 6 отличается, поскольку сначала вычисляется по каждому проекту, а затем усредняется; обе агрегации показывают один и тот же механизм — значительное уменьшение потерянных связей.")

    doc.add_paragraph("6.3 Операционные затраты", style="Heading 2")
    add_table_caption(doc, 8, "Время, токены и оценочная стоимость на DEV20")
    add_table(doc, ["Режим", "Медиана времени", "p95 времени", "Средние токены", "Средние вызовы", "Средняя стоимость"], [
        ["Один вызов", "16,1 с", "20,7 с", "10 565", "1,00", "$0,0069"],
        ["Полный граф", "56,3 с", "90,6 с", "62 046", "11,82", "$0,0346"],
    ], widths=[2.8, 2.6, 2.3, 2.7, 2.5, 2.6])
    add_text(doc, "Полный граф требует примерно в 3,5 раза больше медианного времени и в 5,9 раза больше токенов. Стоимость является расчётной по сохранённой телеметрии и тарифам провайдера, а не значением банковского счёта. Дополнительный расход оправдан только там, где нужен автоматически принимаемый и объяснимый комплект.")

    doc.add_paragraph("6.4 Масштабирование на проектах руководителя", style="Heading 2")
    add_figure(doc, figs["scaling"], 4, "Сквозная успешность в четырёх группах размера", width_cm=15.6)
    add_table_caption(doc, 9, "E2E-успех по числу функциональных требований")
    add_table(doc, ["Группа", "Проектов", "Один вызов", "Полный граф"], [
        ["6–10 ФТ", "5", "5/5", "5/5"],
        ["12–19 ФТ", "5", "4/5", "5/5"],
        ["24–48 ФТ", "5", "0/5", "5/5"],
        ["54–74 ФТ", "5", "0/5", "4/5"],
        ["Итого", "20", "9/20", "19/20"],
    ], widths=[4.3, 3.0, 4.0, 4.0])
    add_text(doc, "Парная разность E2E составляет +0,50; 95%-й ДИ [+0,30; +0,70], точное двустороннее p = 0,001953. У одиночного вызова успешность исчезает начиная с группы 24–48 ФТ, тогда как полный граф сохраняет 19/20 принимаемых комплектов. Единственный отказ FULL на SCALE-018 является контролируемым: после двух исправлений одна из 44 диаграмм сохранила неподтверждённую ветвь и структурный дефект решения, поэтому итоговый gate отклонил комплект.")

    doc.add_paragraph("6.5 Вклад критика", style="Heading 2")
    add_figure(doc, figs["critic"], 5, "Сравнение полного графа и режима без постоянного критика", width_cm=15.5)
    add_text(doc, "Оба режима завершили 60/60 запусков. Наибольшая наблюдаемая разность — Branch F1 +0,034, но 95%-й ДИ [−0,015; +0,088] включает ноль. Среднее число вызовов составило 11,82 для FULL и 7,82 без критика; токены — 62 046 и 47 098. Следовательно, постоянный критик на DEV20 не доказал отдельного прироста и должен запускаться условно: при сложном случае или содержательном сомнении после формальных проверок. Вывод предварителен, поскольку сохранённые режимы получены на разных программных ревизиях организации контрольных точек.")

    doc.add_paragraph("6.6 Переносимость между моделями", style="Heading 2")
    add_figure(doc, figs["models"], 6, "Диагностический пилот на одном простом проекте, три повтора", width_cm=14.8)
    add_text(doc, "DeepSeek выбран как доступная модель для массовых повторов, GPT-5.5 и Claude Opus 5 — как сильные модели двух независимых провайдеров. Такой выбор отделяет вклад архитектуры от эффекта одной модели. На B1-DEV-002 FULL изменил E2E DeepSeek с 0/3 на 3/3; у GPT-5.5 и Claude оба режима дали 3/3. У GPT-5.5 Milestone F1 был выше у одиночного вызова, у Claude — у полного графа. Это один простой кейс, поэтому результат подтверждает совместимость, но не ранжирует модели.")

    doc.add_paragraph("6.7 Проверка программной реализации", style="Heading 2")
    add_text(doc, "Автоматический набор содержит 87 тестов; все тесты прошли 16 сентября 2026 г. Отдельный mutation-suite обнаружил 15 из 15 заранее подготовленных классов структурных и трассировочных дефектов. Это означает 100%-е обнаружение только для заявленного набора мутаций и не является доказательством обнаружения любого возможного смыслового дефекта.")

    add_major_heading(doc, "7 Обсуждение результатов")
    add_text(doc, "Практический результат работы — не просто изображение диаграммы. Кодирующий агент и пользователь получают типизированные процессы, явные входные требования, альтернативы и проверяемые связи. Пользователь может согласовать более дешёвые сценарии и диаграммы до генерации кода; кодирующий и тестирующий агенты получают основу для декомпозиции и проверок.")
    add_text(doc, "Эксперименты не подтверждают тезис «граф всегда умнее одного запроса». На простом входе сильная модель может сразу выдать корректный результат, а постоянная критика может не окупаться. Подтверждён более точный тезис: при одинаковой модели полный граф значительно повышает вероятность получить целый, структурно допустимый и трассируемый комплект, особенно при росте входа.")
    add_text(doc, "Низкие Milestone и Branch F1 показывают оставшуюся исследовательскую проблему: Gold и модель могут по-разному выбирать уровень детализации и границы ветвлений. Повышать итоговую оценку только за счёт промпта нельзя; требуется независимая экспертная проверка допустимых эквивалентов и отдельный анализ дробления шагов.")

    add_major_heading(doc, "8 Ограничения и угрозы достоверности")
    add_bullets(doc, [
        "Gold-разметка DEV20 является авторской технической разметкой; Gold-кандидат размерного набора ожидает проверки двумя независимыми экспертами.",
        "Hidden10 не использовался для настройки и не вскрывался; внешняя валидность на нём пока не заявляется.",
        "На размерном наборе выполнен один запуск на проект; нужен минимум трёхкратный повтор после экспертного freeze.",
        "Содержательные метрики зависят от правил эквивалентности, уровня декомпозиции и качества Gold.",
        "Сравнение трёх моделей выполнено на одном простом проекте и служит пилотом переносимости, а не рейтингом моделей.",
        "Сравнение критика использует результаты разных программных ревизий; для причинного вывода нужен повторный контролируемый запуск одной ревизии.",
        "Расчётная стоимость зависит от тарифов и кэширования провайдера; её следует пересчитывать по сохранённым токенам.",
        "Pyreverse, GitDiagram и DeepWiki не являются прямыми количественными baseline, поскольку начинают с кода или репозитория."
    ])

    add_major_heading(doc, "9 Воспроизводимость и развёртывание")
    add_text(doc, "Репозиторий содержит фиксированные зависимости, MIT License, README, офлайн-проверку GitHub Actions, единый интерфейс командной строки, тестовые наборы, конфигурации и сохранённые результаты. API-ключи не входят в репозиторий. Базовый запуск выполняется в изолированном окружении; платный режим требует явного разрешения --allow-live.")
    add_table_caption(doc, 10, "Основные команды воспроизведения")
    add_table(doc, ["Действие", "Команда"], [
        ["Установка", "poetry install"],
        ["Проверка тестов", "poetry run pytest -q"],
        ["Одиночный и полный эксперимент", "poetry run python scripts/run_benchmark_experiment.py --help"],
        ["Проверка сохранённого эксперимента", "poetry run python scripts/verify_saved_experiment.py --help"],
        ["Построение итоговых таблиц и рисунков", "poetry run python scripts/build_final_size_and_critic_evidence.py"],
    ], widths=[5.0, 10.5])
    add_text(doc, "Открытый репозиторий: https://github.com/ArtemBotsman/agent_langgraph_diagrams. Публичный репозиторий не должен содержать .env, ключи, абсолютные локальные пути, закрытую Gold-разметку hidden-набора или необезличенные ответы провайдеров.")

    add_major_heading(doc, "ЗАКЛЮЧЕНИЕ")
    add_text(doc, "Разработан полный технологический контур от SpecificationReq до вариантов использования, историй, диаграмм деятельности, Mermaid, трассировки и отчёта качества. Реализованы два специализированных LangGraph-агента, корневой оркестратор, типизированные контракты, детерминированные валидаторы, семантическая критика, ограниченное исправление, сохранение состояния и воспроизводимый экспериментальный контур.")
    add_text(doc, "На DEV20 × 3 полный граф достиг 60/60 E2E против 2/60 у одиночного вызова и повысил макро Trace F1 с 0,835 до 0,963. На 20 проектах руководителя размером 6–74 ФТ полный граф завершил 19/20 против 9/20, что даёт статистически значимую парную разность +0,50. Эти данные подтверждают технологическую ценность графа как надёжного проверяемого этапа до кодогенерации, но не доказывают универсальное смысловое превосходство на любых моделях.")
    add_text(doc, "Дальнейшая работа: независимая проверка Gold двумя экспертами и оценка согласия; трёхкратные повторы на размерном наборе; однократный sealed hidden-run после научного freeze; исследование причин снижения Milestone/Branch F1 у GPT-5.5; сравнение лимитов 0, 1, 2, 3 и 4 исправления; условный запуск критика после формальной проверки; проверка ещё более крупных входов и пакетное сохранение после каждой диаграммы.")

    add_major_heading(doc, "СПИСОК ИСПОЛЬЗОВАННЫХ ИСТОЧНИКОВ")
    references = [
        "1. Ferrari A., Abualhaija S., Arora C. Model Generation with LLMs: From Requirements to UML Sequence Diagrams // Proceedings of the 32nd IEEE International Requirements Engineering Conference Workshops. 2024. С. 291–300. DOI: 10.1109/REW61692.2024.00044.",
        "2. Giannouris P., Ananiadou S. NOMAD: A Multi-Agent LLM System for UML Class Diagram Generation from Natural Language Requirements. arXiv:2511.22409. 2025. URL: https://arxiv.org/abs/2511.22409.",
        "3. Baryshnikov O., Alekseev A. M., Nikolenko S. I. Query2Diagram: Answering Developer Queries with UML Diagrams. arXiv:2604.23816. 2026. URL: https://arxiv.org/abs/2604.23816.",
        "4. Zhang W., Jiang B., Fu Y. et al. Large language models in model-driven engineering: a systematic mapping study // Empirical Software Engineering. Опубликовано 16.07.2026. DOI: 10.1007/s10664-026-10921-4.",
        "5. Object Management Group. Unified Modeling Language, Version 2.5.1. 2017. URL: https://www.omg.org/spec/UML/2.5.1/.",
        "6. ISO/IEC/IEEE 29148:2018. Systems and software engineering — Life cycle processes — Requirements engineering.",
        "7. LangChain. LangGraph documentation. URL: https://docs.langchain.com/oss/python/langgraph/overview.",
        "8. Mermaid. Flowchart syntax. URL: https://mermaid.js.org/syntax/flowchart.html.",
        "9. Pylint. Pyreverse documentation. URL: https://pylint.readthedocs.io/en/latest/additional_tools/pyreverse.html.",
        "10. GitDiagram: repository-to-diagram tool. URL: https://github.com/ahmedkhaleel2004/gitdiagram.",
        "11. DeepWiki Open: repository-to-wiki and diagram system. URL: https://github.com/AsyncFuncAI/deepwiki-open.",
        "12. ГОСТ 7.32–2017. Отчёт о научно-исследовательской работе. Структура и правила оформления.",
    ]
    for ref in references:
        add_text(doc, ref, indent=False, align=WD_ALIGN_PARAGRAPH.LEFT)

    add_major_heading(doc, "ПРИЛОЖЕНИЕ А. Карта файлов воспроизведения")
    add_table(doc, ["Назначение", "Путь в репозитории"], [
        ["Контролируемый набор 30 проектов", "benchmark/v1_0_synthetic/"],
        ["Набор руководителя 20 проектов", "benchmark/size_scaling_v1/"],
        ["Результаты DEV20 × 3", "artifacts/benchmark_runs/b1-dev20-r3-deepseek-flash-2026-09-13/ и full-dev20-r3-deepseek-flash-2026-09-13/"],
        ["Итоговая статистика DEV20", "artifacts/final_dev20_statistical_evidence_2026-09-13/"],
        ["Масштабирование и критик", "artifacts/final_experiment_evidence_2026-09-16/"],
        ["Три модели", "artifacts/final_experiment_suite_2026-09-16/"],
        ["Основной запуск", "scripts/run_benchmark_experiment.py"],
        ["Оценка внешней модели", "scripts/evaluate_external_model_outputs.py"],
        ["Сборка данного отчёта", "scripts/build_final_report_gost_2026_09_16.py"],
    ], widths=[5.3, 10.2])
    add_text(doc, "Контрольная дата приведённых результатов — 16 сентября 2026 г. Сохранённые исходные ответы и диагностические отказы не удалялись; повторные платные вызовы для подготовки отчёта не выполнялись.", italic=True)

    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DELIVERABLES / "AgentLangGraph_technology_report_GOST_2026-09-16.docx")
    parser.add_argument("--toc-pages", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    toc_pages = json.loads(args.toc_pages.read_text(encoding="utf-8")) if args.toc_pages else None
    build_report(args.output, toc_pages=toc_pages)
    print(args.output)


if __name__ == "__main__":
    main()
