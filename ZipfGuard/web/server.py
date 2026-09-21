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
from core.data import load_count_json, write_count_json
from core.rockyou import aggregate_rockyou, aggregate_rockyou_withcount
from experiments.pipeline import run_pipeline

DEFAULT_ROCKYOU = ROOT.parent / "lab_basic_50_dicts" / "Rockyou.txt"


def _default_frequency_corpus():
    candidates = (
        ROOT.parent / "rockyou-withcount.txt",
        ROOT.parents[1] / "rockyou-withcount.txt",
    )
    return next((path for path in candidates if path.is_file()), candidates[0])


DEFAULT_FREQUENCY_CORPUS = _default_frequency_corpus()
CACHE = ROOT / "demo_data" / "rockyou_top_2000.json"
_cache_lock = threading.Lock()


def _json_safe(result):
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def rockyou_result(max_lines=1_000_000, top_k=2_000, bootstrap=40):
    payload = aggregate_rockyou(DEFAULT_ROCKYOU, max_lines=max_lines, top_k=top_k)
    return run_pipeline(payload, bootstrap_repetitions=bootstrap)



from web.presentation import report_html, STYLE
from experiments.config import load_config, validate_config
from core.data import validate_count_payload
from hashlib import sha256

INDEX = "<!doctype html><html lang=zh-CN><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>ZipfGuard 实验台</title><style>" + STYLE + "</style>" + r'''<body><main><h1>ZipfGuard · 离线实验台</h1><p>统一 Python 实验核心 · 合成机制演示与聚合分布分析</p>
<section><h2>实验设置</h2><div class="grid">
<label>预设<select id="preset"><option value="quick">快速演示 · 1,000 用户</option><option value="full">完整实验 · 20,000 用户 + 可选 PCFG</option></select></label>
<label>数据来源<select id="source"><option value="synthetic">合成用户</option><option value="rockyou-frequency">RockYou 带频率语料（仅分布分析）</option><option value="rockyou">RockYou 去重字典（仅条目分析）</option><option value="upload">上传聚合 JSON（仅分布分析）</option></select></label>
<label>随机种子<input id="seed" type="number" min="0"></label><label>样本规模<input id="size" type="number" min="100"></label>
<label>Zipf 指数<input id="exponent" type="number" step="0.01"></label><label>攻击预算（逗号分隔）<input id="budgets"></label>
<label>Bootstrap 次数<input id="bootstrap" type="number" min="20"></label><label>风险阈值 q<input id="q" type="number" step="0.01"></label>
</div><div class="grid" id="attackers"></div><div class="grid">
<label>PCFG 生成上限<input id="limit" type="number"></label><label>PCFG 超时秒数<input id="timeout" type="number"></label>
<label>用户响应<select id="response"><option value="repair">修补优先，再尝试短语</option><option value="phrase">短语优先，再尝试修补</option></select></label>
<label>响应成本权重（其余为规则成本）<input id="weight" type="number" min="0" max="1" step="0.05"></label><label>策略选择预算<input id="riskbudget" type="number"></label>
<label>来源类型<select id="semantics"><option value="unknown">未确认</option><option value="frequency">原始重复行频次</option><option value="unique_dictionary">去重字典</option></select></label>
<label><span id="maxlines-label">普通 RockYou 读取行数</span><input id="maxlines" type="number" value="1000000"></label><label>保留 top-k<input id="topk" type="number" value="2000"></label>
<label>聚合文件<input id="upload" type="file" accept=".json"></label></div>
<details><summary>待比较策略（可编辑 JSON；保留 baseline）</summary><textarea id="policies"></textarea></details>
<details><summary>完整配置（可修改词表、搜索动作、响应顺序和约束；点击应用后再运行）</summary><textarea id="config"></textarea><button id="apply">应用完整配置</button><button id="export">下载当前配置</button></details>
<p><button id="run">运行实验</button> <button id="download" disabled>下载结果与 SHA-256</button> <span id="status" role="status"></span></p>
<p class="muted">PassLLM 尚未接入主评估。可选模型失败会明确排除；不会冒充其他模型。</p></section></main><div id="result"></div>
<script>
const $=id=>document.getElementById(id);let cfg=null,last=null;
function put(c){cfg=c;$('seed').value=c.seed;$('size').value=c.synthetic.size;$('exponent').value=c.synthetic.exponent;$('budgets').value=c.budgets.join(',');$('bootstrap').value=c.bootstrap_repetitions;$('q').value=c.q;$('limit').value=c.pcfg.generation_limit;$('timeout').value=c.pcfg.timeout_seconds;$('weight').value=c.search.response_cost_weight;$('riskbudget').value=c.search.risk_budget;$('response').value=c.response.order[0]==='random-phrase'?'phrase':'repair';$('policies').value=JSON.stringify(c.comparison_policies,null,2);$('config').value=JSON.stringify(c,null,2);$('attackers').replaceChildren();for(const [id,label] of [['frequency','频次'],['synthetic-dictionary','合成字典'],['character-ngram','字符 n-gram'],['pcfg','PCFG']]){const l=document.createElement('label');l.textContent=label;const s=document.createElement('select');s.id='att-'+id;for(const [v,t] of [['off','不参与'],['required','必选'],['optional','可选']]){const o=new Option(t,v);s.add(o)}s.value=c.attackers[id]||'off';l.append(s);$('attackers').append(l)}}
function get(){const c=structuredClone(cfg);c.seed=+$('seed').value;c.synthetic.size=+$('size').value;c.synthetic.exponent=+$('exponent').value;c.budgets=$('budgets').value.split(',').map(Number);c.bootstrap_repetitions=+$('bootstrap').value;c.q=+$('q').value;c.pcfg.generation_limit=+$('limit').value;c.pcfg.timeout_seconds=+$('timeout').value;c.search.response_cost_weight=+$('weight').value;c.search.rule_cost_weight=1-c.search.response_cost_weight;c.search.risk_budget=+$('riskbudget').value;const expected=$('response').value==='phrase'?'random-phrase':'append-symbol';if(c.response.order[0]!==expected)c.response.order=$('response').value==='phrase'?['random-phrase','append-symbol','append-symbol-digit']:['append-symbol','append-symbol-digit','random-phrase'];c.comparison_policies=JSON.parse($('policies').value);c.attackers={};for(const id of ['frequency','synthetic-dictionary','character-ngram','pcfg']){const mode=$('att-'+id).value;if(mode!=='off')c.attackers[id]=mode}return c}
async function preset(){try{const r=await fetch('/api/config/'+$('preset').value);put(await r.json())}catch(e){$('status').textContent=e.message}}
function syncSource(){const frequency=$('source').value==='rockyou-frequency';$('maxlines').disabled=frequency;$('semantics').disabled=frequency;$('maxlines-label').textContent=frequency?'完整扫描（无需行数上限）':'普通 RockYou 读取行数';if(frequency&&$('topk').value==='2000')$('topk').value='10000'}
function download(name,text){const a=document.createElement('a'),url=URL.createObjectURL(new Blob([text],{type:'application/octet-stream'}));a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
$('preset').onchange=preset;$('source').onchange=syncSource;$('apply').onclick=()=>{try{put(JSON.parse($('config').value));$('status').textContent='配置已应用'}catch(e){$('status').textContent=e.message}};$('export').onclick=()=>{try{download('experiment.json',JSON.stringify(get(),null,2))}catch(e){$('status').textContent=e.message}};
$('run').onclick=async()=>{$('run').disabled=true;$('download').disabled=true;$('status').textContent='正在计算…';$('result').replaceChildren();last=null;try{const c=get();$('config').value=JSON.stringify(c,null,2);let payload=null;if($('source').value==='upload'){const f=$('upload').files[0];if(!f)throw Error('请选择聚合 JSON 文件');payload=JSON.parse(await f.text())}const res=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({config:c,source:$('source').value,payload,max_lines:+$('maxlines').value,top_k:+$('topk').value,source_semantics:$('semantics').value})});const data=await res.json();if(!res.ok)throw Error(data.error);last=data;$('result').innerHTML=data.html;$('download').disabled=false;$('status').textContent='实验完成'}catch(e){$('status').textContent='未完成：'+e.message}finally{$('run').disabled=false}};
$('download').onclick=()=>{download('zipfguard_report.json',last.json);download('zipfguard_report.json.sha256',last.sha256+'  zipfguard_report.json\n')};syncSource();preset();
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
                return self._send(_json_safe({
                    "rockyou_present": DEFAULT_ROCKYOU.is_file(),
                    "rockyou_bytes": DEFAULT_ROCKYOU.stat().st_size if DEFAULT_ROCKYOU.exists() else 0,
                    "rockyou_frequency_present": DEFAULT_FREQUENCY_CORPUS.is_file(),
                    "rockyou_frequency_bytes": DEFAULT_FREQUENCY_CORPUS.stat().st_size if DEFAULT_FREQUENCY_CORPUS.exists() else 0,
                    "passllm": runtime_status(config),
                }))
            if path.startswith("/api/config/"):
                preset = path.rsplit("/", 1)[-1]
                if preset not in ("quick", "full"): raise ValueError("未知预设")
                return self._send(_json_safe(load_config(preset=preset)))
            if path == "/api/demo": return self._send(_json_safe(run_pipeline(bootstrap_repetitions=40)))
            if path == "/api/rockyou": return self._send(_json_safe(rockyou_result()))
            return self._send(b"not found", "text/plain; charset=utf-8", 404)
        except Exception as exc:
            return self._send(_json_safe({"error": str(exc)}), status=500)

    def do_POST(self):
        if urlparse(self.path).path != "/api/run":
            return self._send(b"not found", "text/plain", 404)
        # Local UI accepts JSON only; reject cross-site browser writes.
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            return self._send(b"forbidden", "text/plain", 403)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8_000_000:
                raise ValueError("请求大小无效")
            request = json.loads(self.rfile.read(length))
            with _cache_lock:
                result = execute_request(request)
            content = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
            return self._send(_json_safe({"result": result, "html": report_html(result, document=False),
                "json": content, "sha256": sha256(content.encode("utf-8")).hexdigest()}))
        except (ValueError, TypeError, KeyError) as exc:
            return self._send(_json_safe({"error": str(exc)}), status=400)
        except Exception as exc:
            return self._send(_json_safe({"error": str(exc)}), status=500)

    def log_message(self, format, *args):
        return


def execute_request(request):
    config = validate_config(request["config"])
    source = request.get("source", "synthetic")
    payload = None
    if source == "rockyou-frequency":
        if not DEFAULT_FREQUENCY_CORPUS.is_file():
            raise ValueError("未找到根目录 rockyou-withcount.txt")
        top_k = request.get("top_k", 10_000)
        if type(top_k) is not int or not 2 <= top_k <= 100_000:
            raise ValueError("网页保留 top-k 须在 2 到 100000 之间")
        payload = aggregate_rockyou_withcount(
            DEFAULT_FREQUENCY_CORPUS,
            top_k=top_k,
        )
    elif source == "rockyou":
        max_lines, top_k = request.get("max_lines", 1_000_000), request.get("top_k", 2000)
        if type(max_lines) is not int or not 20 <= max_lines <= 10_000_000:
            raise ValueError("读取行数须在 20 到 10000000 之间")
        payload = aggregate_rockyou(DEFAULT_ROCKYOU, max_lines=max_lines, top_k=top_k,
                                  source_semantics=request.get("source_semantics", "unknown"))
    elif source == "upload":
        payload = validate_count_payload(request.get("payload"))
    elif source != "synthetic":
        raise ValueError("未知数据来源")
    if payload is not None:
        config["attackers"].pop("pcfg", None)
        if not config["attackers"]:
            config["attackers"] = {"frequency": "required"}
    return run_pipeline(payload, config=config)


def main():
    parser = argparse.ArgumentParser(description="ZipfGuard local demo UI")
    parser.add_argument("--host", default="127.0.0.1"); parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(); server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"ZipfGuard demo: http://{args.host}:{args.port}")
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__ == "__main__": main()
