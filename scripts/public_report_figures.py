"""Offline, vector figures for the technical report; values come from the snapshot."""
from statistics import mean

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors

BLUE = colors.HexColor('#087da5')
ORANGE = colors.HexColor('#e97817')
GREY = colors.HexColor('#dddddd')


def panel(labels, series, title, maximum=1, value_digits=3, ticks=None):
    """Two-series bar chart. Zero origin and explicit units/title; no truncated axes."""
    d = Drawing(460, 235)
    d.add(String(230, 222, title, fontName='TNRB', fontSize=12, textAnchor='middle'))
    for i, (name, _, color) in enumerate(series):
        x = 100 + i*155
        d.add(Rect(x, 201, 9, 9, fillColor=color, strokeColor=None))
        d.add(String(x+14, 202, name, fontName='TNR', fontSize=10))
    left, bottom, width, height = 40, 29, 408, 153
    if ticks is None:
        ticks = [maximum*i/4 for i in range(5)]
    for tick in ticks:
        y = bottom + height*tick/maximum
        d.add(Line(left, y, left+width, y, strokeColor=GREY, strokeWidth=.5))
        label = str(int(tick)) if maximum > 1 else f'{tick:.2f}'.replace('.', ',')
        d.add(String(left-6, y-3, label, fontName='TNR', fontSize=9, textAnchor='end'))
    d.add(Line(left, bottom, left+width, bottom, strokeColor=colors.black, strokeWidth=.6))
    band = width/len(labels)
    bar_width = min(39, band*.29)
    for i, label in enumerate(labels):
        center = left + band*(i+.5)
        d.add(String(center, 11, label, fontName='TNR', fontSize=10, textAnchor='middle'))
        for j, (_, values, color) in enumerate(series):
            value = values[i]
            assert value is not None and 0 <= value <= maximum
            x = center + (j-1)*bar_width
            h = value/maximum*height
            d.add(Rect(x, bottom, bar_width-1, h, fillColor=color, strokeColor=None))
            text = f'{value:.{value_digits}f}'.replace('.', ',')
            d.add(String(x+(bar_width-1)/2, bottom+h+4, text,
                         fontName='TNR', fontSize=9, textAnchor='middle'))
    return d


def large_values(data, fr, metric):
    rows = data['large_cap2']['rows']
    return [next(r for r in rows if r['fr_count'] == fr and r['method'] == method)
            for method in ['OPENCODE_BUILD_TYPED', 'FULL_NEW']]


def grouped_mean(data, lo, hi, method, key):
    rows = data['sizes_original24']['rows']
    projects = sorted({r['case_id'] for r in rows if lo <= r['fr_count'] <= hi})
    project_means = []
    for project in projects:
        values = []
        for repeat in [1, 2]:
            pair = [r for r in rows if r['case_id'] == project and r['repeat_id'] == repeat]
            if len(pair) == 2 and all(r.get('usage_complete') and r.get('metrics')
                                     and r['metrics'].get(key) is not None for r in pair):
                values.append(next(r['metrics'][key] for r in pair if r['method'] == method))
        if values:
            project_means.append(mean(values))
    return mean(project_means)


def charts(name, data):
    if name == 'large':
        figures = []
        keys = ['actor', 'uc', 'milestone', 'branch', 'trace']
        labels = ['Акторы', 'UC', 'Этапы', 'Ветви', 'Trace']
        for fr in [59, 74]:
            rows = large_values(data, fr, None)
            series = [(method, [r['metrics'][k+'_f1'] for k in keys], color)
                      for r, method, color in zip(rows, ['OpenCode', 'FULL'], [BLUE, ORANGE])]
            figures.append(panel(labels, series, f'{fr} ФТ: все пять F1 по кандидату Gold'))
        return figures
    if name == 'resources':
        figures = []
        for key, scale, title, maximum, digits in [
            ('elapsed_seconds', 60, 'Время отдельного запуска, мин', 20, 2),
            ('cost_estimate_usd', 1, 'Цена отдельного запуска, $', .4, 3),
        ]:
            series = []
            for i, (method, color) in enumerate([('OpenCode', BLUE), ('FULL', ORANGE)]):
                values = [large_values(data, fr, None)[i][key]/scale for fr in [59, 74]]
                series.append((method, values, color))
            figures.append(panel(['59 ФТ', '74 ФТ'], series, title, maximum, digits))
        return figures
    if name == 'sizes':
        figures = []
        groups = [(6,10), (12,19), (24,48)]
        for metric, title in [('milestone_f1', 'Этапы: Milestone F1'),
                              ('milestone_recall', 'Этапы: Milestone Recall')]:
            series = [(label, [grouped_mean(data, lo, hi, method, metric) for lo, hi in groups], color)
                      for method, label, color in [('OPENCODE_BUILD_TYPED','OpenCode',BLUE),
                                                  ('FULL_NEW','FULL',ORANGE)]]
            figures.append(panel(['6–10 ФТ','12–19 ФТ','24–48 ФТ'], series, title))
        return figures
    if name == 'temperature':
        rows = data['temperature_pilot']['rows']
        finished, accepted, unstarted = [], [], []
        for temperature in [0, .2, .7]:
            group = [r for r in rows if r['temperature'] == temperature]
            assert len(group) == 8
            finished.append(sum(r['status'] == 'completed' for r in group))
            accepted.append(sum(r.get('formal_pass') is True for r in group))
            unstarted.append(sum(r['status'] == 'not_started' for r in group))
        return [
            panel(['T=0','T=0,2','T=0,7'], [('Завершено',finished,BLUE),('Не начато',unstarted,GREY)],
                  'Полнота сетки: по 8 попыток в плане',8,0),
            panel(['T=0','T=0,2','T=0,7'], [('Завершено',finished,BLUE),('Принято формально',accepted,ORANGE)],
                  'Число исходов, не рейтинг температуры',8,0),
        ]
    raise ValueError(name)
