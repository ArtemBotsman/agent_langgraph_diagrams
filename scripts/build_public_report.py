"""Build the public technical report offline from its text and numeric snapshot.

Requires reportlab and pypdf; no API calls or downloads are performed.
"""
from pathlib import Path
from statistics import mean
import json
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle
from pypdf import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / 'docs/final/results/results_snapshot.json').read_text())['series']
FONT_ROOT = Path('/System/Library/Fonts/Supplemental')
if not (FONT_ROOT / 'Times New Roman.ttf').exists():
    raise SystemExit('Set FONT_ROOT to a local Times New Roman font directory; no download is attempted.')
for name, filename in [('TNR', 'Times New Roman.ttf'), ('TNRB', 'Times New Roman Bold.ttf')]:
    pdfmetrics.registerFont(TTFont(name, str(FONT_ROOT / filename)))
pdfmetrics.registerFontFamily('TNR', normal='TNR', bold='TNRB', italic='TNR', boldItalic='TNRB')
BODY = ParagraphStyle('body', fontName='TNR', fontSize=14, leading=21,
                      alignment=TA_JUSTIFY, firstLineIndent=1.25*cm, spaceAfter=4)
HEAD = ParagraphStyle('head', parent=BODY, fontName='TNRB', firstLineIndent=0,
                      alignment=TA_LEFT, spaceBefore=5, spaceAfter=13, keepWithNext=True)
TITLE = ParagraphStyle('title', parent=HEAD, fontSize=16, leading=24, alignment=TA_CENTER)
CELL = ParagraphStyle('cell', fontName='TNR', fontSize=10.5, leading=12.6)
SMALL = ParagraphStyle('small', parent=CELL, fontSize=9.5, leading=11.4)
WIDTH = A4[0] - 4.5*cm

def table(rows, widths, small=False):
    style = SMALL if small else CELL
    cells = [[Paragraph(escape(str(value)), style) for value in row] for row in rows]
    t = Table(cells, colWidths=[WIDTH*x for x in widths], repeatRows=1, hAlign='LEFT')
    t.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), .4, colors.black),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#eeeeee')),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
        ('TOPPADDING', (0,0), (-1,-1), 4 if not small else 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4 if not small else 3),
    ]))
    return [t, Spacer(1, 10)]

def method(r):
    return 'FULL' if r['method'] == 'FULL_NEW' else 'OpenCode'

def f(value, digits=3):
    return 'NA' if value is None else f'{value:.{digits}f}'.replace('.', ',')

def generated(name):
    if name == 'roles':
        return table([
            ['Граф', 'Генератор', 'Критик', 'Редактор'],
            ['Use Cases', 'Создаёт сценарии из требований', 'Проверяет содержание и согласованность', 'Исправляет текущие замечания'],
            ['Activity', 'Строит граф по UC', 'Сверяет диаграмму с UC и источником', 'Исправляет диаграмму'],
        ], [.18,.27,.29,.26])
    if name == 'setup':
        return table([
            ['Параметр', 'Оба метода в новых cap2/размерных сериях'],
            ['Модель / параметры', 'deepseek-flash; T=0,2; thinking disabled'],
            ['На один ответ', 'До 131072 выходных токенов'],
            ['На попытку', 'До $2 и 512 вызовов; 3600 с активного выполнения'],
            ['Токены суммарно', 'Отдельный потолок не задан; действует бюджет'],
            ['Остановка', 'Расход начатых вызовов учитывается после остановки'],
            ['Оценка', 'Одинаковый контракт, Gold и matcher после генерации'],
        ], [.3,.7])
    if name == 'large_metrics':
        rows = [['ФТ / метод', 'Метрика', 'P', 'R', 'F1']]
        for r in DATA['large_cap2']['rows']:
            for key,label in [('actor','Actor'),('uc','UC'),('milestone','Milestone'),('branch','Branch'),('trace','Trace')]:
                rows.append([f"{r['fr_count']} / {method(r)}", label] +
                            [f(r['metrics'][key+'_'+suffix]) for suffix in ['precision','recall','f1']])
        return table(rows, [.28,.24,.16,.16,.16], small=True)
    if name == 'large_resources':
        rows = [['ФТ / метод','Секунды','Вызовы','Токены','Цена, $']]
        for r in DATA['large_cap2']['rows']:
            rows.append([f"{r['fr_count']} / {method(r)}", f(r['elapsed_seconds'],1),
                         r['calls'], f"{r['tokens']:,}".replace(',',' '), f(r['cost_estimate_usd'],6)])
        return table(rows,[.25,.16,.15,.23,.21],small=True)
    if name == 'large_structure':
        rows = [['ФТ / метод','Цепочки','V2','Ссылка','Служебный','Явное допущение']]
        for r in DATA['large_cap2']['rows']:
            a=r['activity_v2']; cat=a['exclusive_categories']
            rows.append([f"{r['fr_count']} / {method(r)}", f"{r['fr_with_action_chain']}/{r['fr_count']}",
                         f"{a['supported']}/{a['total']}",cat['valid_declared_reference'],
                         cat['structural_without_reference_or_unsupported'],cat['unsupported_without_reference']])
        return table(rows,[.23,.15,.15,.14,.17,.16],small=True)
    if name == 'size_metrics':
        rows = [['Группа','Метрика','FULL P/R/F1','OpenCode P/R/F1']]
        source=DATA['sizes_original24']['rows']
        for lo,hi in [(6,10),(12,19),(24,48)]:
            cases=sorted({r['case_id'] for r in source if lo<=r['fr_count']<=hi})
            for metric,label in [('actor','Actor'),('uc','UC'),('milestone','Milestone'),('branch','Branch'),('trace','Trace')]:
                values=[]
                for meth in ['FULL_NEW','OPENCODE_BUILD_TYPED']:
                    scores=[]
                    for suffix in ['precision','recall','f1']:
                        key=metric+'_'+suffix
                        project_means=[]
                        for case in cases:
                            pair_values=[]
                            for repeat in [1,2]:
                                pair=[r for r in source if r['case_id']==case and r['repeat_id']==repeat]
                                if len(pair)==2 and all(r.get('usage_complete') and r.get('metrics') and r['metrics'].get(key) is not None for r in pair):
                                    pair_values.append(next(r['metrics'][key] for r in pair if r['method']==meth))
                            if pair_values:
                                project_means.append(mean(pair_values))
                        scores.append(f(mean(project_means)) if project_means else 'NA')
                    values.append(' / '.join(scores))
                rows.append([f'{lo}–{hi} ФТ',label,*values])
        return table(rows,[.16,.18,.33,.33],small=True)
    if name == 'hashes':
        rows=[['Контрольный срез','SHA-256 исходного summary.json']]
        for key, series in DATA.items():
            digest=series['source_summary_sha256']
            rows.append([key, digest[:32]+' '+digest[32:]])
        return table(rows,[.34,.66],small=True)
    raise ValueError(name)

def page_number(canvas, doc):
    if doc.page > 1:
        canvas.setFont('TNR',12)
        canvas.drawCentredString(A4[0]/2, 1.15*cm, str(doc.page))

def build():
    source=(ROOT/'docs/final/REPORT_SOURCE.md').read_text()
    story=[]
    pages=source.split('<!-- page -->')
    for i,page in enumerate(pages):
        if i:
            story.append(PageBreak())
        else:
            story.append(Spacer(1,2*cm))
        for block in page.strip().split('\n\n'):
            block=block.strip()
            if not block:
                continue
            if block.startswith('@'):
                story.extend(generated(block[1:]))
            elif block.startswith('# '):
                story.append(Paragraph(escape(block[2:]),TITLE))
                story.append(Spacer(1,1.2*cm))
            elif block.startswith('## '):
                story.append(Paragraph(escape(block[3:]),HEAD))
            elif i==0:
                style=ParagraphStyle('cover',parent=BODY,alignment=TA_CENTER,firstLineIndent=0)
                story.append(Paragraph(escape(block),style))
                story.append(Spacer(1,1.3*cm))
            else:
                story.append(Paragraph(escape(block.replace('\n',' ')),BODY))
    output=ROOT/'docs/final/deliverables/AgentLangGraph_technology_report_GOST.pdf'
    draft=output.with_suffix('.tmp.pdf')
    doc=SimpleDocTemplate(str(draft),pagesize=A4,leftMargin=3*cm,rightMargin=1.5*cm,
                          topMargin=2*cm,bottomMargin=2*cm,title='AgentLangGraph: технический отчёт',
                          author='Боцман Артём')
    doc.build(story,onFirstPage=page_number,onLaterPages=page_number)
    writer=PdfWriter()
    writer.append(PdfReader(draft))
    writer.add_metadata({'/Title':'AgentLangGraph: технический отчёт','/Author':'Боцман Артём'})
    # Do not publish wall-clock metadata; experimental durations remain in tables.
    for key in ['/CreationDate','/ModDate']:
        if key in writer.metadata:
            del writer._info.get_object()[key]
    with output.open('wb') as stream:
        writer.write(stream)
    draft.unlink()
    print(output)
    print('Pages:',len(PdfReader(output).pages))

if __name__=='__main__':
    build()
