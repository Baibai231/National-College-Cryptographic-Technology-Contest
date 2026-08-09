"""Diagnose which specific line in findLoginLinks causes stale element"""
import sys, time
sys.path.insert(0, '.')
from utils.util_test_password import _get_shared_driver
from utils.login_link_discovery import LoginLinkDiscovery

driver = _get_shared_driver()
discovery = LoginLinkDiscovery(driver)
discovery.inject_scripts()

driver.get('https://github.com')
time.sleep(3)

# Re-inject for current page
discovery._scripts_injected = False
discovery.inject_scripts()

# Test minimal queries
tests = [
    # Simplest: just query all 'a' elements
    'var els=document.querySelectorAll("a"); return els.length;',
    # Access basic props
    'var els=document.querySelectorAll("a"); var r=[]; for(var i=0;i<Math.min(5,els.length);i++){r.push(els[i].tagName)} return r;',
    # Access innerText
    'var els=document.querySelectorAll("a"); var r=[]; for(var i=0;i<Math.min(5,els.length);i++){r.push((els[i].innerText||"").substring(0,10))} return r;',
    # Access href
    'var els=document.querySelectorAll("a"); var r=[]; for(var i=0;i<Math.min(5,els.length);i++){r.push(els[i].getAttribute("href")||"")} return r;',
    # Access title
    'var els=document.querySelectorAll("a"); var r=[]; for(var i=0;i<Math.min(5,els.length);i++){r.push(els[i].title||"")} return r;',
    # Access ariaLabel
    'var els=document.querySelectorAll("a"); var r=[]; for(var i=0;i<Math.min(5,els.length);i++){r.push(els[i].ariaLabel||"")} return r;',
    # Full query with all element types but minimal props
    'var els=document.querySelectorAll("a,span,button,div,iframe,frame"); var r=[]; for(var i=0;i<Math.min(5,els.length);i++){r.push({tag:els[i].tagName,txt:(els[i].innerText||"").substring(0,10)})} return r;',
    # Full query iterating ALL elements
    'var els=document.querySelectorAll("a,span,button,div"); return els.length;',
]

for idx, test in enumerate(tests):
    try:
        result = driver.execute_script(test)
        print(f'Test {idx}: OK -> {str(result)[:80]}')
    except Exception as e:
        print(f'Test {idx}: ERROR -> {str(e)[:100]}')
        break

driver.quit()
