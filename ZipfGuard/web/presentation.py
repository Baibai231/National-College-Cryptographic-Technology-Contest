"""Shared escaped HTML/SVG presentation for both UIs; no experiment logic."""
import html
import json
import math

COLORS = ["#2563eb", "#e16b24", "#189b80", "#a855b5", "#cc4255", "#667a15", "#087d99", "#8d6849"]
STYLE = """
body{margin:0;color:#20304a;background:#f3f6fb;font:15px system-ui,sans-serif}
main{max-width:1220px;margin:auto;padding:24px}h1{font-size:29px}h2{font-size:21px;margin:0 0 16px}
section{background:#fff;border:1px solid #dbe3ef;border-radius:14px;padding:24px;margin:18px 0;overflow:auto}
.muted{color:#62728a;font-size:13px}.notice{padding:15px;background:#fff5d9;border-radius:10px;margin:12px 0}
.metrics{display:flex;gap:28px;flex-wrap:wrap}.metric strong{display:block;font-size:25px;margin-top:6px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;border-bottom:1px solid #e4eaf2;padding:10px;white-space:nowrap}
th{background:#f7f9fc}svg{width:100%;max-height:430px;min-width:500px}.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12px}
summary{cursor:pointer;margin:12px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}
button,select,input,textarea{font:inherit;border:1px solid #bdcce0;border-radius:7px;padding:8px}button{background:#2463d9;color:white;cursor:pointer}
label{display:inline-flex;flex-direction:column;gap:5px;margin:8px}textarea{width:95%;height:160px}.grid{display:flex;flex-wrap:wrap;gap:10px}
"""


def escape(value):
    return html.escape(str(value))


def table(headers, rows):
    return "<table><thead><tr>" + "".join(f"<th>{escape(h)}</th>" for h in headers) + "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{escape(v)}</td>" for v in row) + "</tr>" for row in rows) + "</tbody></table>"


def rate(value):
    return f"{100 * value:.2f}%"


def interval(value, bounds):
    return f"{rate(value)} [{rate(bounds['lower'])}, {rate(bounds['upper'])}]"


def plot(series, *, xlabel, ylabel, log=False, scatter=False):
    points = [(x, y) for _, values in series for x, y, *_ in values]
    if not points:
        return "<p>没有可用数据。</p>"
    tx = (lambda x: math.log10(max(x, 1))) if log else (lambda x: x)
    xs, ys = [tx(x) for x, _ in points], [y for _, y in points]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(0, min(ys)), max(ys)
    if xmax == xmin: xmax = xmin + 1
    if ymax == ymin: ymax = ymin + 1
    if ymin < 0: ymin *= 1.1
    ymax *= 1.08
    def xy(x, y):
        return 75 + 765 * (tx(x) - xmin) / (xmax - xmin), 325 - 275 * (y - ymin) / (ymax - ymin)
    svg = ['<svg viewBox="0 0 890 385" role="img" aria-label="' + escape(ylabel + ' / ' + xlabel) + '">']
    for i in range(6):
        value = ymin + (ymax - ymin) * i / 5
        py = 325 - 275 * i / 5
        svg.append(f'<path d="M75 {py}H840" stroke="#e5ebf3"/><text x="65" y="{py+4}" text-anchor="end" font-size="11" fill="#607087">{value:.3f}</text>')
        vx = xmin + (xmax - xmin) * i / 5
        label = 10**vx if log else vx
        px = 75 + 765 * i / 5
        svg.append(f'<text x="{px}" y="345" text-anchor="middle" font-size="11" fill="#607087">{label:.3g}</text>')
    for i, (name, values) in enumerate(series):
        color = COLORS[i % len(COLORS)]
        coords = [xy(row[0], row[1]) for row in values]
        if not scatter:
            svg.append(f'<polyline fill="none" stroke="{color}" stroke-width="2.5" points="' + ' '.join(f'{x:.2f},{y:.2f}' for x, y in coords) + '"/>')
        for row, (px, py) in zip(values, coords):
            tooltip = row[2] if len(row) > 2 else f"{name}: {row[0]:.5g}, {row[1]:.5g}"
            svg.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="{5 if scatter else 2}" fill="{color}"><title>{escape(tooltip)}</title></circle>')
    svg.append(f'<text x="460" y="375" text-anchor="middle" font-size="13">{escape(xlabel)}{"（对数刻度）" if log else ""}</text><text x="75" y="25" font-size="13">{escape(ylabel)}</text></svg>')
    svg.append('<div class="legend">' + ''.join(f'<span style="color:{COLORS[i % len(COLORS)]}">● {escape(name)}</span>' for i, (name, _) in enumerate(series)) + '</div>')
    return ''.join(svg)


def budget_plot(series, *, ylabel="攻击成功率"):
    return plot(series, xlabel="猜测预算 K", ylabel=ylabel, log=True) + '<details><summary>查看线性坐标</summary>' + plot(series, xlabel="猜测预算 K", ylabel=ylabel) + '</details>'


def report_html(result, *, document=True):
    a, metadata = result['analysis'], result['metadata']
    parts = ['<main><section><h1>ZipfGuard · 实验结果</h1><div class="metrics">']
    source = result['dataset'].get('metadata', {})
    total_label = "保留频次数" if source.get('source_semantics') == 'frequency_counts' else "样本数"
    for label, value in (("数据集", result['dataset']['dataset_id']), (total_label, result['dataset']['total_count']), ("选择模型", a['selected_model']), (f"q={a['risk_threshold']['q']:.1%} 风险排名", a['risk_threshold']['model_rank'])):
        parts.append(f'<div class="metric">{escape(label)}<strong>{escape(value)}</strong></div>')
    boundary = (
        "公开泄露语料仅用于聚合频率分布分析；不代表独立攻击验证或用户改密效果。"
        if source.get('source_semantics') == 'frequency_counts' else
        "合成有限空间和预设用户行为下的机制演示，不代表真实世界防御效果；Wilson 区间为逐点区间。"
    )
    parts += ['</div><p class="muted">' + escape(metadata.get('evaluation_scope', '')) + '</p>', '<p class="muted">' + boundary + '</p></section>']
    if not result.get('simulation'):
        parts.append('<section><h2>聚合数据 · 仅运行分布分析</h2><div class="notice">M2 攻击、M3 用户响应和 M4 策略搜索均未运行：输入只有聚合频次，没有固定划分的用户口令及行为数据。</div>')
        parts.append(table(['来源属性', '记录'], [(name, source.get(key, '未提供 / 未确认')) for name, key in [('数据来源','source_type'), ('原始频次 / 去重字典','source_semantics'), ('是否去重','input_deduplicated'), ('读取行数','source_lines_read'), ('有效行数','observed_valid_lines'), ('空行数','blank_lines'), ('异常行数','invalid_lines'), ('空白口令字段行','empty_or_whitespace_password_lines'), ('含控制字节口令行','password_control_byte_lines'), ('原始总频次','observed_frequency_total'), ('保留总频次','retained_frequency_total'), ('保留类别数','retained_categories'), ('top-k','top_k'), ('截断概率质量','truncated_mass'), ('频次顺序异常','frequency_order_increases'), ('文件哈希','source_sha256'), ('频次解释','frequency_interpretation'), ('分析范围','analysis_scope')]]))
        if source.get('all_observed_counts_one') or source.get('source_semantics') == 'unique_dictionary':
            parts.append('<div class="notice">观测为每项一次或用户声明去重字典：下面仅描述条目计数，不可用于推断真实用户口令频率。</div>')
        parts.append('</section>')
    parts.append('<section><h2>分布拟合与残差</h2>')
    parts.append(table(['模型','验证对数似然','KS','BIC'], [(m['id'], f"{m['validation_log_likelihood']:.3f}", f"{m['validation_ks']:.4f}", f"{m['bic']:.3f}") for m in a['models']]))
    curves = a['curves']
    series = [(label, [(r['rank'], r[key]) for r in curves]) for label, key in [('经验 CDF','empirical_cdf')] + [(m['id'],m['id']+'_cdf') for m in a['models']]]
    parts.append(plot(series, xlabel='排名', ylabel='累计概率', log=True))
    parts.append('<details><summary>查看线性坐标</summary>' + plot(series, xlabel='排名', ylabel='累计概率') + '</details>')
    parts.append(plot([(m['id'], [(r['rank'], r[m['id']+'_cdf'] - r['empirical_cdf']) for r in curves]) for m in a['models']], xlabel='排名', ylabel='残差：模型 CDF − 经验 CDF', log=True) + '</section>')
    baseline = result.get('attack_baselines')
    if baseline:
        parts.append('<section><h2>M2 · 统一攻击基线</h2>')
        budgets = baseline['budgets']
        rows = []
        for attack in baseline['attacks']:
            e, att = attack['evaluation'], attack['attacker']
            p = att['parameters']
            rows.append([att['label'], e['candidate_count'], interval(e['coverage'], e['coverage_interval'])] + [interval(pt['rate'], pt['interval']) for pt in e['points']] + [p.get('generated_count','—'), p.get('matched_candidates','—'), p.get('generation_limit','—')])
        parts.append(table(['攻击器','候选数','候选覆盖率 [95% CI]'] + [f'cracked@{b} [95% CI]' for b in budgets] + ['原始生成数','匹配数','生成上限'], rows))
        parts.append(budget_plot([(r['attacker']['label'], [(p['budget'],p['rate']) for p in r['evaluation']['points']]) for r in baseline['attacks']]))
        parts.append('</section><section><h2>M3 · 用户响应与冻结 / 自适应对照</h2>')
        parts.append(table(['策略','初始接受率','完成率','修改率','冻结风险','自适应风险'], [(r['policy']['name'], rate(r['initial_accept_rate']),rate(r['accept_rate']),rate(r['modification_rate']),rate(r['frozen_risk']),rate(r['adaptive_risk'])) for r in result['policies']]))
        for row in result['policies']:
            parts.append('<details open><summary>' + escape(row['policy']['name']) + '</summary>' + budget_plot([(label,[(p['budget'],p[key]) for p in row['worst_case']]) for label,key in [('最坏冻结','frozen_rate'),('最坏自适应','adaptive_rate')]]) + '</details>')
        parts.append('</section>')
    search = result.get('policy_search')
    if search:
        parts.append('<section><h2>M4 · 策略风险与用户成本</h2>')
        front = set(search['pareto_front'])
        groups = [('Pareto 前沿', lambda r:r['policy']['name'] in front), ('可行候选', lambda r:r['feasible'] and r['policy']['name'] not in front), ('超出约束',lambda r:not r['feasible'])]
        parts.append(plot([(name,[(r['costs']['total_cost'],r['adaptive_risk'],r['policy']['name']) for r in search['validation_candidates'] if pred(r)]) for name,pred in groups], xlabel='用户与规则总成本（validation）',ylabel='最坏自适应风险（validation）',scatter=True))
        parts.append(f"<p>候选 {search['candidate_count']} · 可行 {search['feasible_count']} · Pareto {search['pareto_count']} · 选择预算 {search['config']['risk_budget']}</p>")
        if not search['selected_tiers']:
            parts.append('<div class="notice">当前约束下无策略达到最低收益，不生成推荐。</div>')
        parts.append(table(['档位','策略','验证风险','测试风险','测试风险下降','测试修改率'],[(r['tier'],r['policy']['name'],rate(r['validation']['adaptive_risk']),rate(r['test']['adaptive_risk']),rate(r['test']['security_gain']),rate(r['test']['response']['modification_rate'])) for r in search['selected_tiers']]))
        parts.append('</section>')
    parts.append('<section><h2>模型参与状态与复现</h2>')
    parts.append('<p>实际参与：' + escape(', '.join(metadata.get('participating_attackers',[])) or '无：聚合模式') + '</p>')
    pcfg = metadata.get('pcfg',{})
    parts.append('<p>PCFG：环境 ' + ('可检测' if pcfg.get('available') else '不可用') + '；本实验 ' + ('已参与' if pcfg.get('enabled') else '未参与') + '</p>')
    parts.append('<p>PassLLM：环境可检测；尚未接入主评估；当前实验未使用 PassLLM。</p>')
    for failure in metadata.get('attacker_failures',[]):
        parts.append('<div class="notice">' + escape(failure['attacker_id'] + ' 未参与最坏攻击者比较。原因：' + failure['reason']) + '</div>')
    parts.append('<details><summary>完整配置、数据 / 源码哈希、Git、Python 与依赖版本</summary><pre>' + escape(json.dumps(result.get('reproducibility',{}),ensure_ascii=False,indent=2)) + '</pre></details></section></main>')
    body = ''.join(parts)
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>' + STYLE + '</style><body>' + body + '</body></html>' if document else body
