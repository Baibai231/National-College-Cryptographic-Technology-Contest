"""Test iframe/frame access causes stale element"""
import sys, time
sys.path.insert(0, '.')
from utils.util_test_password import _get_shared_driver
from utils.login_link_discovery import LoginLinkDiscovery

driver = _get_shared_driver()
discovery = LoginLinkDiscovery(driver)

driver.get('https://github.com')
time.sleep(3)

discovery._scripts_injected = False
discovery.inject_scripts()

tests = [
    # iframe only
    ('var els=document.querySelectorAll("iframe"); return els.length;', 'iframe count'),
    # frame only
    ('var els=document.querySelectorAll("frame"); return els.length;', 'frame count'),
    # iframe with innerText
    ('var els=document.querySelectorAll("iframe"); var r=[]; for(var i=0;i<els.length;i++){r.push(els[i].tagName)} return r;', 'iframe tags'),
    # full query with iframe+frame but only tagName
    ('var els=document.querySelectorAll("a,span,button,div,iframe,frame"); return els.length;', 'all elements count'),
    # Full query: tagName only for all
    ('var els=document.querySelectorAll("a,span,button,div,iframe,frame"); var r=[]; for(var i=0;i<els.length;i++){r.push(els[i].tagName)} return r.slice(0,5);', 'all tags'),
    # REGEX test
    ('var rx=/login/i; var el=document.querySelector("a"); var h=el.getAttribute("href"); return h + " | " + String(h).match(rx);', 'regex test'),
    # innerText regex match
    ('var rx=/login/i; var els=document.querySelectorAll("a"); var cnt=0; for(var i=0;i<els.length;i++){if(els[i].innerText && els[i].innerText.match(rx))cnt++} return cnt;', 'innerText regex count'),
    # title regex match
    ('var rx=/login/i; var els=document.querySelectorAll("a"); var cnt=0; for(var i=0;i<els.length;i++){if(els[i].title && els[i].title.match(rx))cnt++} return cnt;', 'title regex count'),
]

for expr, label in tests:
    try:
        result = driver.execute_script(expr)
        print(f'{label}: OK -> {str(result)[:100]}')
    except Exception as e:
        print(f'{label}: ERROR -> {str(e)[:150]}')

print()
print('Now testing the ACTUAL findLoginLinks function...')
try:
    result = driver.execute_script('return findLoginLinks(false);')
    print(f'findLoginLinks(false): OK, len={len(result) if result else 0}')
except Exception as e:
    print(f'findLoginLinks(false): ERROR -> {str(e)[:200]}')

driver.quit()
