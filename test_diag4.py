"""CDP-only: isolate findLoginLinks stale element"""
import sys, time
sys.path.insert(0, '.')
from utils.util_test_password import _get_shared_driver

driver = _get_shared_driver()

# CDP-only injection
with open('utils/js/scripts.js', 'r', encoding='utf-8') as f:
    scripts_js = f.read()
with open('utils/js/form_detection_addons.js', 'r', encoding='utf-8') as f:
    addons_js = f.read()

driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': scripts_js})
driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': addons_js})
print('CDP scripts registered')

driver.get('https://github.com')
time.sleep(3)

# Check which functions exist
for fn in ['ruleset', 'gPt', 'findLoginLinks', 'detectEmailInputs']:
    t = driver.execute_script('return typeof ' + fn + ';')
    print(f'{fn}: {t}')

# Now test findLoginLinks via Runtime.evaluate (CDP direct) instead of execute_script
print('\nTesting via CDP Runtime.evaluate...')
result = driver.execute_cdp_cmd('Runtime.evaluate', {
    'expression': 'findLoginLinks(false)',
    'returnByValue': True
})
if 'exceptionDetails' in result:
    print(f'CDP ERROR: {result["exceptionDetails"].get("text", "?")}')
elif 'result' in result:
    val = result['result'].get('value', '?')
    if isinstance(val, list):
        print(f'CDP OK: len={len(val)}')
        if val:
            print(f'  first: {str(val[0])[:150]}')
else:
    print(f'CDP result: {result}')

# Also test via execute_script
print('\nTesting via execute_script...')
try:
    r = driver.execute_script('return findLoginLinks(false);')
    print(f'execute_script OK: len={len(r) if r else 0}')
except Exception as e:
    print(f'execute_script ERROR: {str(e)[:150]}')

driver.quit()
