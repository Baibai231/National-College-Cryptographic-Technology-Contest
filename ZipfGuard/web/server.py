"""Zero-dependency local demo server.

Run from the ZipfGuard directory::

    python web/server.py --port 8765

It serves an interactive dashboard and JSON endpoints. The browser never sees
raw Rockyou strings; the server returns only counts, model metrics and policy
aggregates.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai.passllm_adapter import PassLLMConfig, runtime_status
from core.data import load_count_json, synthetic_counts, write_count_json
from core.rockyou import aggregate_rockyou
from experiments.pipeline import run_pipeline

DEFAULT_ROCKYOU = ROOT.parent / "lab_basic_50_dicts" / "Rockyou.txt"
CACHE = ROOT / "demo_data" / "rockyou_top_2000.json"
_cache_lock = threading.Lock()


def _json_safe(result):
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def rockyou_result(max_lines=1_000_000, top_k=2_000, bootstrap=40):
    cache_current = CACHE.exists() and (not DEFAULT_ROCKYOU.exists() or CACHE.stat().st_mtime >= DEFAULT_ROCKYOU.stat().st_mtime)
    if cache_current and max_lines == 1_000_000 and top_k == 2_000:
        payload = load_count_json(CACHE)
    else:
        payload = aggregate_rockyou(DEFAULT_ROCKYOU, max_lines=max_lines, top_k=top_k)
        if max_lines == 1_000_000 and top_k == 2_000:
            write_count_json(payload, CACHE)
    return run_pipeline(payload, bootstrap_repetitions=bootstrap)


INDEX = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ZipfGuard DP-HTPG</title><style>
body{margin:0;background:#f5f7fb;color:#172033;font:15px system-ui,-apple-system,"Segoe UI",sans-serif}main{max-width:1180px;margin:auto;padding:28px}h1{margin:0 0 6px;font-size:30px}h2{margin-top:28px}.sub{color:#61708a}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card,.panel{background:white;border:1px solid #e2e8f0;border-radius:12px;padding:16px;box-shadow:0 2px 8px #1720330a}.metric{font-size:25px;font-weight:700;margin-top:8px}.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:18px 0}button{background:#2563eb;color:white;border:0;border-radius:8px;padding:10px 14px;cursor:pointer}button.secondary{background:#475569}button:disabled{opacity:.55}table{border-collapse:collapse;width:100%;background:white}th,td{text-align:left;border-bottom:1px solid #e8edf4;padding:9px}th{color:#526177;font-weight:600}.pill{display:inline-block;border-radius:999px;background:#e8f1ff;color:#1557bd;padding:4px 9px;font-size:12px}.warn{background:#fff4d6;color:#8a5b00}.chart{height:240px;width:100%;background:linear-gradient(180deg,#fff,#f8fafc);border-radius:8px}.small{font-size:12px;color:#64748b}.error{color:#b42318}.status{margin-left:auto}@media(max-width:800px){.grid{grid-template-columns:repeat(2,1fr)}}
</style></head><body><main><h1>ZipfGuard <span class="pill">DP-HTPG</span></h1><div class="sub">面向 AI 攻击的动态口令策略风险实验 · 仅离线聚合数据</div>
<div class="toolbar"><button id="demo">加载合成演示</button><button id="rock" class="secondary">加载 Rockyou 聚合</button><span id="status" class="status small"></span></div>
<section class="grid" id="metrics"></section><section class="panel"><h2>经验 CDF 与模型摘要</h2><canvas id="chart" class="chart"></canvas><div id="models"></div></section>
<section class="panel"><h2>策略 What-if</h2><div id="policies"></div></section><section class="panel"><h2>运行边界</h2><p class="small">Rockyou 只在服务器端流式读取并聚合；浏览器收到的是频次、模型指标和策略统计，不返回明文候选。PassLLM 权重仅在配置了 Torch/Transformers/PEFT 且基座存在时启用，否则显示 n-gram 回退。</p><pre id="backend" class="small"></pre></section>
</main><script>
const $=id=>document.getElementById(id); let last=null;
function cell(v){return v==null?'—':typeof v==='number'?v.toLocaleString(undefined,{maximumFractionDigits:4}):v}
function table(headers,rows){return '<table><thead><tr>'+headers.map(h=>'<th>'+h+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(v=>'<td>'+cell(v)+'</td>').join('')+'</tr>').join('')+'</tbody></table>'}
function draw(points){const c=$('chart'),x=c.getContext('2d'),w=c.width=c.clientWidth*devicePixelRatio,h=c.height=c.clientHeight*devicePixelRatio;x.clearRect(0,0,w,h); if(!points.length)return; const ys=points.map(p=>p.empirical_cdf),max=Math.max(...ys,1); x.strokeStyle='#2563eb';x.lineWidth=3*devicePixelRatio;x.beginPath();points.forEach((p,i)=>{const px=i/(points.length-1)*w,py=h-(p.empirical_cdf/max)*(h-18*devicePixelRatio)-8*devicePixelRatio;i?x.lineTo(px,py):x.moveTo(px,py)});x.stroke();x.fillStyle='#526177';x.font=12*devicePixelRatio+'px sans-serif';x.fillText('经验累计质量（横轴为排名）',10,20)}
function renderPolicies(r){
  $('policies').innerHTML=table(['策略','状态','安全收益','样本拒绝率','接受率','总数/接受/拒绝/评估','攻击器'],r.policies.map(p=>[
    p.policy.name,p.evaluation_status==='evaluated'?'可评估':'无法评估',
    p.security_gain==null?'无法评估':p.security_gain,p.user_cost,p.accept_rate,
    ['total','accepted','rejected','evaluated'].map(k=>p.sample_counts[k]).join('/'),p.attacker
  ]));
  const note=document.createElement('p'); note.className='small';
  note.textContent='全部被拒绝的策略没有可评估样本，不能计算安全收益，也不参与推荐。样本拒绝率不是实测用户负担。'
    + (r.recommendations.some(x=>x.tier==='高防护')?'':' 当前没有可推荐的正收益高防护策略。');
  $('policies').appendChild(note);
}
function render(r){last=r; const a=r.analysis,t=a.risk_threshold; $('metrics').innerHTML=[['数据集',r.dataset.dataset_id],['样本',r.dataset.total_count],['选择模型',a.selected_model],['q=1%排名',t.model_rank]].map(([k,v])=>'<div class="card"><div class="small">'+k+'</div><div class="metric">'+cell(v)+'</div></div>').join(''); $('models').innerHTML=table(['模型','验证对数似然','KS','BIC'],a.models.map(m=>[m.id,m.validation_log_likelihood,m.validation_ks,m.bic])); renderPolicies(r); draw(a.curves); $('backend').textContent=JSON.stringify(r.metadata,null,2)+'\n\n推荐：\n'+JSON.stringify(r.recommendations,null,2)}
async function load(url){$('status').textContent='计算中…';$('demo').disabled=$('rock').disabled=true;try{const res=await fetch(url);if(!res.ok)throw Error(await res.text());render(await res.json());$('status').textContent='完成'}catch(e){$('status').innerHTML='<span class="error">'+e.message+'</span>'}finally{$('demo').disabled=$('rock').disabled=false}}
$('demo').onclick=()=>load('/api/demo');$('rock').onclick=()=>load('/api/rockyou');fetch('/api/status').then(r=>r.json()).then(s=>{$('backend').textContent='后端状态：\\n'+JSON.stringify(s,null,2)}).catch(e=>{$('status').textContent=e.message});
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, content_type="application/json; charset=utf-8", status=200):
        self.send_response(status); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path == "/": return self._send(INDEX.encode("utf-8"), "text/html; charset=utf-8")
            if path == "/api/status":
                config = PassLLMConfig.workspace_default(ROOT.parent)
                return self._send(_json_safe({"rockyou_present": DEFAULT_ROCKYOU.is_file(), "rockyou_bytes": DEFAULT_ROCKYOU.stat().st_size if DEFAULT_ROCKYOU.exists() else 0, "passllm": runtime_status(config)}))
            if path == "/api/demo": return self._send(_json_safe(run_pipeline(synthetic_counts(), bootstrap_repetitions=40)))
            if path == "/api/rockyou": return self._send(_json_safe(rockyou_result()))
            return self._send(b"not found", "text/plain; charset=utf-8", 404)
        except Exception as exc:
            return self._send(_json_safe({"error": str(exc)}), status=500)

    def log_message(self, format, *args):
        return


def main():
    parser = argparse.ArgumentParser(description="ZipfGuard local demo UI")
    parser.add_argument("--host", default="127.0.0.1"); parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(); server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"ZipfGuard demo: http://{args.host}:{args.port}")
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__ == "__main__": main()
