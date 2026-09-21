"""Optional real-browser acceptance check; requires Playwright and local Edge."""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from core.data import synthetic_counts

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
    page = browser.new_page(viewport={'width':1440,'height':1000},device_scale_factor=1)
    errors=[]
    page.on('pageerror',lambda exc: errors.append(str(exc)))
    page.goto('http://127.0.0.1:8765/')
    page.wait_for_function("document.getElementById('seed').value === '42'")
    page.locator('#preset').select_option('full')
    page.wait_for_function("document.getElementById('size').value === '20000'")
    assert page.locator('#att-pcfg').input_value() == 'optional'
    page.locator('#preset').select_option('quick')
    page.wait_for_function("document.getElementById('size').value === '1000'")
    page.screenshot(path=str(ROOT/'reports/section1_controls.png'),full_page=True)
    page.locator('#run').click()
    page.wait_for_function("document.getElementById('status').textContent === '实验完成'",timeout=900000)
    assert page.locator('#result svg').count() >= 12
    assert page.get_by_role('heading',name='M2 · 统一攻击基线').count()==1
    page.locator('#result section').filter(has=page.get_by_role('heading',name='M2 · 统一攻击基线')).screenshot(path=str(ROOT/'reports/section1_m2.png'))
    response=page.evaluate('last.result')
    (ROOT/'reports/section1_browser_quick.json').write_text(json.dumps(response,ensure_ascii=False,indent=2),encoding='utf-8')
    page.locator('#source').select_option('upload')
    payload=synthetic_counts(size=100,categories=10)
    page.locator('#upload').set_input_files({'name':'counts.json','mimeType':'application/json','buffer':json.dumps(payload).encode()})
    page.locator('#run').click()
    page.wait_for_function("document.getElementById('status').textContent === '实验完成'",timeout=60000)
    assert page.get_by_role('heading',name='M2 · 统一攻击基线').count()==0
    assert '均未运行' in page.locator('#result').inner_text()
    page.locator('#upload').set_input_files({'name':'bad.json','mimeType':'application/json','buffer':b'bad'})
    page.locator('#run').click()
    page.wait_for_function("document.getElementById('status').textContent.startsWith('未完成')")
    assert page.locator('#result').inner_text()==''
    assert page.locator('#download').is_disabled()
    assert not errors,errors
    summary={'browser':browser.version,'javascript_errors':errors,'checks':['full/quick presets','actual quick pipeline','M2 confidence intervals and graphs','aggregate upload module visibility','invalid upload clears stale results'],'quick_runtime_ms':response['metadata']['runtime_ms'],'quick_participants':response['metadata']['participating_attackers']}
    (ROOT/'reports/section1_browser_checks.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))
    browser.close()
