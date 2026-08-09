"""Quick test of JS injection and link discovery"""
import sys, time
sys.path.insert(0, '.')
from utils.util_test_password import _get_shared_driver
from utils.login_link_discovery import LoginLinkDiscovery

driver = _get_shared_driver()
discovery = LoginLinkDiscovery(driver)
discovery.inject_scripts()

# Test on about:blank
driver.get('about:blank')
time.sleep(0.5)
print('=== about:blank ===')
for expr in ['findLoginLinks(false)', 'findLoginLinksByCoords()', 'getLoginLinkAttrs()']:
    try:
        r = driver.execute_script('return ' + expr + ';')
        print(f'  {expr}: OK, len={len(r) if r else 0}')
    except Exception as e:
        print(f'  {expr}: ERROR - {e}')

# Test on github
print('\n=== github.com ===')
driver.get('https://github.com')
time.sleep(3)
for expr in ['findLoginLinks(false)', 'getLoginLinkAttrs()', 'detectEmailInputs(document)']:
    try:
        r = driver.execute_script('return ' + expr + ';')
        length = len(r) if r else 0
        print(f'  {expr}: OK, len={length}')
        if r and length > 0:
            first = r[0]
            tag = first.get('tagName', '?')
            text = str(first.get('innerText', ''))[:40]
            print(f'    first: tag={tag}, text={text}')
    except Exception as e:
        print(f'  {expr}: ERROR - {str(e)[:120]}')

driver.quit()
