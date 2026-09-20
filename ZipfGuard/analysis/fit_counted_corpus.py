"""Offline descriptive rank-distribution audit. Never exports password strings.

Input: ASCII decimal count, one separator byte, then password bytes.
All ranks contribute to grouped multinomial fitting; no top-k truncation.
This is descriptive in-sample fitting, not an independent goodness-of-fit test.
"""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
import math
from pathlib import Path
import re
import time

import numpy as np
from scipy.optimize import minimize, minimize_scalar


def audit(path):
    stats = dict(lines=0, parsed_rows=0, malformed_rows=0, nonpositive_rows=0,
                 empty_rows=0, empty_mass=0, source_mass=0, invalid_utf8_rows=0,
                 whitespace_edge_rows=0, control_byte_rows=0, order_violations=0)
    counts, digests, digest = array('Q'), bytearray(), hashlib.sha256()
    pattern = re.compile(rb'^[ \t]*([0-9]+)[ \t](.*)$')
    previous = None
    with path.open('rb') as handle:
        for raw in handle:
            digest.update(raw)
            stats['lines'] += 1
            # This source uses LF. Remove framing LF only; never strip passwords.
            line = raw[:-1] if raw.endswith(b'\n') else raw
            match = pattern.fullmatch(line)
            if match is None:
                stats['malformed_rows'] += 1
                continue
            count, password = int(match[1]), match[2]
            stats['parsed_rows'] += 1
            stats['source_mass'] += count
            if count <= 0:
                stats['nonpositive_rows'] += 1
                continue
            if not password:
                stats['empty_rows'] += 1
                stats['empty_mass'] += count
                continue
            try:
                password.decode('utf-8', errors='strict')
            except UnicodeDecodeError:
                stats['invalid_utf8_rows'] += 1
            stats['whitespace_edge_rows'] += password[:1].isspace() or password[-1:].isspace()
            stats['control_byte_rows'] += any(c < 32 or c == 127 for c in password)
            if previous is not None and count > previous:
                stats['order_violations'] += 1
            previous = count
            counts.append(count)
            # In-memory uniqueness audit only. Digests are never saved or exposed.
            digests.extend(hashlib.blake2b(password, digest_size=16).digest())
            if stats['lines'] % 5_000_000 == 0:
                print(f"audit scanned {stats['lines']:,} rows", flush=True)
    hashed = np.frombuffer(digests, dtype='V16')
    hashed.sort()
    duplicate_hashes = int(np.count_nonzero(hashed[1:] == hashed[:-1]))
    if duplicate_hashes:
        raise ValueError('Repeated password digests detected; aggregate/verify before fitting')
    values = np.frombuffer(counts, dtype=np.uint64).copy()
    if stats['malformed_rows'] or stats['nonpositive_rows'] or stats['order_violations']:
        raise ValueError(f'Input needs explicit remediation: {stats}')
    stats.update(bytes=path.stat().st_size, sha256=digest.hexdigest(),
                 analyzed_types=len(values), analyzed_mass=int(values.sum()),
                 duplicate_digest_rows=duplicate_hashes,
                 uniqueness_method='128-bit BLAKE2b in memory; zero repeated digests')
    return values, stats


def edges_for(size, extra=4096):
    return np.unique(np.r_[0, np.arange(1, min(size, 10000)+1),
                           np.geomspace(min(size, 10001), size, extra).astype(np.int64), size]).astype(np.int64)


def log_group_mass(name, theta, edges, size):
    lower, upper = edges[:-1] / size, edges[1:] / size
    if name == 'cdf_power':
        a = float(theta[0])
        delta = upper**a - lower**a
        return np.log(delta)
    if name == 'stretched_cdf':
        a, t = float(theta[0]), math.exp(float(theta[1]))
        lo, hi = t * lower**a, t * upper**a
        return -lo + np.log(-np.expm1(-(hi-lo))) - math.log(-math.expm1(-t))
    raise ValueError(name)


def fit_models(values):
    size, total = len(values), int(values.sum())
    edges = edges_for(size)
    group_counts = np.add.reduceat(values, edges[:-1]).astype(float)
    weights = group_counts / total
    logs = np.log(np.arange(1, size+1, dtype=float))

    def zipf_loss(s):
        unnormalized = np.exp(-s*logs)
        groups = np.add.reduceat(unnormalized, edges[:-1])
        return float(-np.dot(weights, np.log(groups / groups.sum())))

    print('fit discrete Zipf on all ranks', flush=True)
    z = minimize_scalar(zipf_loss, bounds=(0.001, 3.0), method='bounded',
                        options={'xatol':1e-9})
    z_norm = float(np.exp(-z.x*logs).sum())
    rows = [dict(id='zipf', label='Discrete Zipf', parameters={'s':float(z.x)},
                 dimensions=1, grouped_nll_per_record=float(z.fun),
                 optimizer_success=bool(z.success), normalizer=z_norm)]
    del logs
    print('fit finite-support CDF power', flush=True)
    c = minimize_scalar(lambda a: -float(np.dot(weights,log_group_mass('cdf_power',[a],edges,size))),
                        bounds=(0.005,1.0),method='bounded',options={'xatol':1e-10})
    rows.append(dict(id='cdf_power',label='Finite-support CDF power',parameters={'a':float(c.x)},
                     dimensions=1,grouped_nll_per_record=float(c.fun),optimizer_success=bool(c.success)))
    print('fit finite-support stretched-exponential CDF (multi-start)',flush=True)
    loss = lambda x: -float(np.dot(weights,log_group_mass('stretched_cdf',x,edges,size)))
    trials=[]
    for a,t in ((.08,.01),(.2,.1),(.4,1),(.6,5),(.9,30)):
        result=minimize(loss,[a,math.log(t)],method='L-BFGS-B',
                        bounds=((.005,1.),(math.log(1e-6),math.log(1000))),
                        options={'ftol':1e-13,'gtol':1e-8,'maxiter':200})
        trials.append(result)
    best=min(trials,key=lambda result:result.fun)
    # Bin-resolution sensitivity check; all records still included.
    fine_edges=edges_for(size,16384)
    fine_weights=np.add.reduceat(values,fine_edges[:-1]).astype(float)/total
    fine=minimize(lambda x:-float(np.dot(fine_weights,log_group_mass('stretched_cdf',x,fine_edges,size))),
                  best.x,method='L-BFGS-B',bounds=((.005,1.),(math.log(1e-6),math.log(1000))),
                  options={'ftol':1e-13,'gtol':1e-8,'maxiter':200})
    rows.append(dict(id='stretched_cdf',label='Finite-support stretched CDF',
                     parameters={'a':float(best.x[0]),'t':float(math.exp(best.x[1]))},dimensions=2,
                     grouped_nll_per_record=float(best.fun),optimizer_success=bool(best.success),
                     start_objectives=[float(r.fun) for r in trials],
                     fine_bin_check={'bins':len(fine_edges)-1,'a':float(fine.x[0]),
                                     't':float(math.exp(fine.x[1])), 'optimizer_success':bool(fine.success)}))
    for row in rows:
        row['grouped_aic']=2*row['dimensions']+2*total*row['grouped_nll_per_record']
    return rows, edges


def pmf_at(row, ranks, size):
    r=np.asarray(ranks,dtype=float)
    p=row['parameters']
    if row['id']=='zipf':
        return np.exp(-p['s']*np.log(r))/row['normalizer']
    # Scalar/vector formula preserves the adjacent-rank bin definition.
    hi,lo=(r/size)**p['a'],((r-1)/size)**p['a']
    if row['id']=='cdf_power':
        return hi-lo
    t=p['t']
    return np.exp(-t*lo)*(-np.expm1(-t*(hi-lo)))/(-math.expm1(-t))


def ols_fit(values, threshold):
    k=int(np.count_nonzero(values>threshold))
    if k<3:
        raise ValueError('Insufficient non-singleton records for HTPG-style regression')
    x=np.log(np.arange(1,k+1,dtype=float));y=np.log(values[:k].astype(float))
    slope,intercept=np.polyfit(x,y,1)
    error=y-(intercept+slope*x)
    alpha=-float(slope);C=math.exp(float(intercept))
    # Maximum curvature of y=C*x^-alpha, in raw rank/count coordinates.
    x0=(C*C*alpha*alpha*(2*alpha+1)/(alpha+2))**(1/(2*alpha+2))
    cutoff=max(1,min(len(values),int(math.floor(x0))))
    return dict(frequency_threshold_exclusive=threshold,fit_types=k,C=C,alpha=alpha,
                log_r_squared=1-float(np.dot(error,error)/np.sum((y-y.mean())**2)),
                curvature_x0=x0,cutoff_floor=cutoff,head_count=int(values[:cutoff].sum()),
                head_share=float(values[:cutoff].sum()/values.sum()))


def measure(values, rows):
    size,total=len(values),int(values.sum())
    points=np.unique(np.r_[1,10,100,1000,10000,100000,1000000,
                           np.geomspace(1,size,1800).astype(int),size])
    points=points[points<=size]
    observed=[];predicted=[[] for _ in rows]
    ecum=0.;mcum=np.zeros(len(rows));ks=np.zeros(len(rows));mae=np.zeros(len(rows))
    kl=np.zeros(len(rows));cross=np.zeros(len(rows));d_rank=np.zeros(len(rows),dtype=int)
    thresholds={str(q):None for q in (.01,.05,.1,.2,.5,.8,.9)}
    for start in range(0,size,250000):
        stop=min(size,start+250000)
        ranks=np.arange(start+1,stop+1,dtype=float)
        counts=values[start:stop].astype(float);emp=counts/total
        ecdf=ecum+np.cumsum(emp);ecum=float(ecdf[-1])
        mask=(points>start)&(points<=stop);idx=points[mask]-start-1
        observed.extend(ecdf[idx].tolist())
        for q in thresholds:
            if thresholds[q] is None and ecdf[-1]>=float(q):
                thresholds[q]=start+int(np.searchsorted(ecdf,float(q)))+1
        for j,row in enumerate(rows):
            prob=pmf_at(row,ranks,size)
            assert np.all(prob>0)
            cdf=mcum[j]+np.cumsum(prob);mcum[j]=float(cdf[-1])
            err=np.abs(cdf-ecdf);i=int(np.argmax(err))
            if err[i]>ks[j]:ks[j]=float(err[i]);d_rank[j]=start+i+1
            mae[j]+=float(err.sum());kl[j]+=float(np.dot(emp,np.log(emp/prob)))
            cross[j]+=-float(np.dot(emp,np.log(prob)))
            predicted[j].extend(cdf[idx].tolist())
    for j,row in enumerate(rows):
        assert abs(mcum[j]-1)<1e-7,(row['id'],mcum[j])
        row.update(max_cdf_error=float(ks[j]),max_cdf_error_rank=int(d_rank[j]),
                   mean_absolute_cdf_error=float(mae[j]/size),empirical_kl_nats=float(kl[j]),
                   cross_entropy_nats=float(cross[j]),full_rank_log_likelihood=-float(total*cross[j]))
    return dict(ranks=points.tolist(),empirical_cdf=observed,model_cdfs=predicted,
                empirical_counts=values[points-1].tolist()),thresholds


def draw(out, values, rows, ols, curves):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    ranks=np.array(curves['ranks']);total=int(values.sum());size=len(values)
    colors=['#2864b7','#cb8230','#21876d']
    fig,axes=plt.subplots(2,2,figsize=(14,9),layout='constrained')
    ax=axes[0,0]
    ax.loglog(ranks,curves['empirical_counts'],color='#252c34',lw=2,label='Observed counts')
    for row,color in zip(rows,colors):
        ax.loglog(ranks,total*pmf_at(row,ranks,size),color=color,lw=1.5,label=row['label'])
    ax.set(title='A. Rank vs count | full observed support',xlabel='Password rank',ylabel='Record count')
    ax.legend(fontsize=8)
    ax=axes[0,1]
    ax.semilogx(ranks,np.array(curves['empirical_cdf'])*100,color='#252c34',lw=2,label='Observed')
    for row,cdf,color in zip(rows,curves['model_cdfs'],colors):
        ax.semilogx(ranks,np.array(cdf)*100,color=color,lw=1.5,label=row['label'])
    ax.set(title='B. Cumulative record coverage',xlabel='Top-ranked password types',ylabel='Coverage (%)',ylim=(0,101))
    ax=axes[1,0]
    for row,cdf,color in zip(rows,curves['model_cdfs'],colors):
        ax.semilogx(ranks,(np.array(cdf)-curves['empirical_cdf'])*100,color=color,lw=1.5,label=row['label'])
    ax.axhline(0,color='#666',lw=.6)
    ax.set(title='C. Model minus observed coverage',xlabel='Password rank',ylabel='Error (percentage points)')
    ax=axes[1,1]
    k=ols['fit_types'];r=np.unique(np.geomspace(1,k,1600).astype(int))
    ax.loglog(r,values[r-1],color='#252c34',lw=2,label='Observed, count > 3')
    ax.loglog(r,ols['C']*r**(-ols['alpha']),color='#8a50a0',lw=1.7,label='HTPG-style log-log OLS')
    ax.axvline(ols['curvature_x0'],color='#bf4f4f',ls='--',label=f"Curvature cut ~ {ols['curvature_x0']:.0f}")
    ax.set(title='D. HTPG-style fit | frequent subset only',xlabel='Password rank',ylabel='Record count')
    ax.legend(fontsize=8)
    for ax in axes.flat:ax.grid(True,alpha=.18)
    fig.suptitle('Rockyou with counts: descriptive distribution audit\n'
                 f'{size:,} nonempty types | {total:,} weighted records | in-sample fits, not attack results',fontsize=14)
    fig.savefig(out/'distribution_fit.png',dpi=170)
    plt.close(fig)


def report(result):
    s=result['audit'];o=result['htpg_ols'];models=result['models'];c=result['concentration']
    lines=['# Rockyou 带频次数据全量分布分析','',
      '日期：2026-09-20。仅做离线描述统计和拟合；不修改口令，不进行猜测攻击，不访问网站。','',
      '## 数据与清理','',
      f"原始 {s['lines']:,} 行，总计数 {s['source_mass']:,}。排除 {s['empty_rows']} 行空口令（权重 {s['empty_mass']:,}）后，分析 {s['analyzed_types']:,} 个非空口令，权重合计 {s['analyzed_mass']:,}。",
      f"坏格式 {s['malformed_rows']} 行；非正计数 {s['nonpositive_rows']} 行；倒序异常 {s['order_violations']}；重复 128 位摘要 {s['duplicate_digest_rows']}。去重检查仅在内存中进行，不导出摘要或原文。",
      f"保留 {s['invalid_utf8_rows']} 行非 UTF-8 字节序列，{s['whitespace_edge_rows']} 行首尾空白、{s['control_byte_rows']} 行控制字节；不替换、不 strip、不 Unicode 归一化。计数列后仅剥离一个分隔字节。",
      f"源文件 SHA-256：`{s['sha256']}`。来源和授权状态不由文件名证明；本数据与论文版本不同。",'',
      '## 真实集中程度','', '| 排名前若干种口令 | 计数占比 |','|---|---:|']
    for k,v in c['top_shares'].items():lines.append(f'| {int(k):,} | {v:.4%} |')
    lines += ['',f"仅出现一次的口令有 {c['singletons']:,} 种，占种类 {c['singleton_type_share']:.2%}，占全部计数 {c['singleton_record_share']:.2%}。",
              '以上是真实频次排序下的经验覆盖，不是训练出的攻击器成绩，也不是独立用户数或当前网站风险。','',
              '## HTPG 风格拟合','',
              '对出现次数大于 3 的条目，做普通最小二乘：ln(f_r) = ln(C) - alpha ln(r)。每个种类等权，不再按其账号计数加权。',
              f"纳入 {o['fit_types']:,} 种；C={o['C']:.8g}，alpha={o['alpha']:.8f}，对数坐标 R²={o['log_r_squared']:.6f}。",
              f"即 f_r ≈ {o['C']:.6g} / r^{o['alpha']:.6f}。原始 rank/count 坐标下的最大曲率位置 x0={o['curvature_x0']:.3f}；本报告向下取整为 {o['cutoff_floor']}，覆盖 {o['head_count']:,} 条计数（{o['head_share']:.4%}）。",
              '与 HTPG 原论文 Rockyou 表格的 C=831682、alpha=0.914、x0=1171 很接近，但论文总计数 32510281 与本文件不同，不能据此宣称数据版本相同或已完整复现论文。',
              f"特别注意最热门端仍有偏差：排名第一实际计数 {round(c['top_shares']['1']*s['analyzed_mass']):,}，拟合预测 {o['C']:.0f}。总体对数 R² 很高，不代表每一排名尤其最头部都准确。",
              '曲率公式：kappa=|f_second|/(1+f_prime²)^(3/2)；解析位置 x0=[C² alpha² (2alpha+1)/(alpha+2)]^[1/(2alpha+2)]。次数换成概率会改变 C 和曲率边界；该边界不是密码强弱真值。',
              '此线仅拟合高频部分，不与全量归一化模型混用 AIC。R² 高不代表全量数据严格服从 Zipf。','',
              '| 排除的低频阈值 | 纳入种类 | alpha | 对数 R² | 曲率位置 |','|---|---:|---:|---:|---:|']
    for a in result['htpg_sensitivity']:
        lines.append(f"| count ≤ {a['frequency_threshold_exclusive']} | {a['fit_types']:,} | {a['alpha']:.6f} | {a['log_r_squared']:.5f} | {a['curvature_x0']:.1f} |")
    lines += ['', '## 全分布模型比较','',
       'K 是观测到的非空种类总数。比较三个在 1..K 上归一化的模型：','',
       '- 离散 Zipf：p(r)=r^(-s)/sum(j^(-s))。',
       '- 有限支持 CDF 幂律：F(r)=(r/K)^a，p(r)=F(r)-F(r-1)。',
       '- 有限支持拉伸指数 CDF：F(r)=[1-exp(-t(r/K)^a)]/[1-exp(-t)]，相邻差得到 p(r)。',
       '', '后两项是有限支持参数化候选，与已有演示代码同类；并非声称逐项复现 Hou/Wang 的原模型及优化协议。',
       f"为降低计算量，在共同的 {result['fit_bins']:,} 个连续排名箱上最大化多项式分组似然：前 10000 名逐项保留，其余对数分箱。所有种类和计数都参与，不是 top-k 子集重归一化。评价时逐一遍历全部排名，计算真实最大 CDF 偏差和完整排名对数似然。",
       '所有拟合和误差均来自同一文件，是样本内描述分析。未执行独立测试集验证、参数重拟合 bootstrap 或 Monte Carlo 拟合优度检验，不报告 KS p 值。','',
       '| 模型 | 参数 | 最大累计偏差 | 经验 KL 距离(nat) | 分组 AIC |',
       '|---|---|---:|---:|---:|']
    for m in models:
        pars=', '.join(f'{k}={v:.6g}' for k,v in m['parameters'].items())
        lines.append(f"| {m['label']} | {pars} | {100*m['max_cdf_error']:.4f} 个百分点 | {m['empirical_kl_nats']:.6f} | {m['grouped_aic']:.2f} |")
    best=min(models,key=lambda m:m['max_cdf_error'])
    likelihood=min(models,key=lambda m:m['grouped_aic'])
    lines += ['',f"最大累计偏差最小：{best['label']}。分组 AIC 最低：{likelihood['label']}。指标优化目标不同，排名可能不同；这只是这三种参数化候选之间的比较。",
              '分组 AIC 是共同分箱下的相对描述分数，不能当作已通过独立拟合优度检验或泛化证明。',
              f"拉伸指数模型细分箱敏感性：{json.dumps(models[-1]['fine_bin_check'],ensure_ascii=False)}。",'',
              '本次拉伸指数拟合的 t 接近零，近似退化为 CDF 幂律，在此有限支持参数化和拟合目标下没有得到实质改善；不代表否定其他参数化或原论文的拉伸指数结论。','',
              '## 限制与下一步','',
              '不把历史泄露数据代表性推广到当前所有网站；计数不等于可识别的独立自然人。频次单例尾部存在有限样本效应。字节口径与论文清理规则差异会改变拟合。',
              '本次不做口令修改或攻击。后续可固定清理及拟合口径，进行头尾特征比较；任何策略效果都需另做隔离训练、验证和测试的攻击实验。',
              '现有网页分析器、M1–M4、正式 reports 目录均未更改，本分析单独保存。','',
              '## 复现','',
              '需要 Python、NumPy、SciPy、Matplotlib。运行：`python fit_counted_corpus.py --input <计数文件> --output <结果目录>`。分析脚本只在内存读取口令字节；输出仅含匿名统计、模型参数和曲线。',
              '输入解析协议：行首可有空格/制表符填充，十进制次数后一个空格或制表符为分隔符，其余字节为口令，LF 为记录边界。本文件无 CRLF。',
              f"运行依赖版本：{json.dumps(result['versions'])}。",'',
              '## 参考方法','',
              '- Xiao and Zeng, Dynamically Generate Password Policy via Zipf Distribution, TIFS 2022, DOI 10.1109/TIFS.2022.3152357：高频过滤、对数线性拟合、曲率头尾划分。',
              '- Hou and Wang, New Observations on Zipf’s Law in Passwords, TIFS 2023, DOI 10.1109/TIFS.2022.3176185：分布比较与误差、拟合优度边界。https://wangdingg.weebly.com/uploads/2/0/3/6/20366987/tifs22-n2-final.pdf','']
    return '\n'.join(lines)


def self_test():
    n=500
    edges=np.arange(n+1)
    for name,theta in [('cdf_power',[.35]),('stretched_cdf',[.4,math.log(2)])]:
        probs=np.exp(log_group_mass(name,theta,edges,n))
        assert np.all(probs>0) and abs(probs.sum()-1)<1e-12
    e=edges_for(500)
    assert e[0]==0 and e[-1]==500 and np.all(np.diff(e)>0)
    alpha,C=.9,800000.
    x=(C*C*alpha*alpha*(2*alpha+1)/(alpha+2))**(1/(2*alpha+2))
    def curvature(r):
        return C*alpha*(alpha+1)*r**(-alpha-2)/(1+(C*alpha*r**(-alpha-1))**2)**1.5
    assert curvature(x)>curvature(x*.99) and curvature(x)>curvature(x*1.01)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    self_test();start=time.monotonic()
    values,stats=audit(args.input)
    print('audit complete',json.dumps(stats),flush=True)
    sensitivity=[ols_fit(values,t) for t in (1,3,5,10,100)]
    ols=sensitivity[1]
    print('HTPG-style fit',json.dumps(ols),flush=True)
    rows,edges=fit_models(values)
    curves,thresholds=measure(values,rows)
    total=int(values.sum());singletons=int(np.count_nonzero(values==1))
    concentration=dict(top_shares={str(k):float(values[:k].sum()/total) for k in (1,10,100,1000,10000,100000,1000000)},
                       singletons=singletons,singleton_type_share=singletons/len(values),
                       singleton_record_share=singletons/total,coverage_rank_thresholds=thresholds)
    import scipy,matplotlib
    result=dict(audit=stats,htpg_ols=ols,htpg_sensitivity=sensitivity,models=rows,
                concentration=concentration,fit_bins=len(edges)-1,curves=curves,
                versions=dict(numpy=np.__version__,scipy=scipy.__version__,matplotlib=matplotlib.__version__),
                method='descriptive in-sample grouped multinomial fits; all observed ranks included',
                elapsed_seconds=round(time.monotonic()-start,2))
    (args.output/'statistics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    draw(args.output,values,rows,ols,curves)
    (args.output/'分析报告.md').write_text(report(result),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='curves'},ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
