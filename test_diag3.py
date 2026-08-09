"""Debug addons JS execution"""
import sys, time
sys.path.insert(0, '.')
from utils.util_test_password import _get_shared_driver

driver = _get_shared_driver()
driver.get('https://github.com')
time.sleep(3)

# Read addons JS
with open('utils/js/form_detection_addons.js', 'r', encoding='utf-8') as f:
    addons_js = f.read()

# First check: can we inject via script tag?
inject_result = driver.execute_script("""
    try {
        var s = document.createElement('script');
        s.textContent = arguments[0];
        document.head.appendChild(s);
        return JSON.stringify({ok: true});
    } catch(e) {
        return JSON.stringify({ok: false, error: e.toString()});
    }
""", addons_js)
print('Injection:', inject_result)

# Check if functions exist now
time.sleep(1)
for fn in ['ruleset', 'findLoginLinks', 'detectEmailInputs', 'getLoginLinkAttrs',
           'isVisible', 'getXPath', 'gPt', 'onTopLayer',
           'email_detector_ruleset', 'combinedLoginLinkRegexLooseSrc']:
    t = driver.execute_script('return typeof ' + fn + ';')
    print(f'  {fn}: {t}')

# Check for JS errors on the page
errors = driver.execute_script("""
    var errs = [];
    var origErr = window.onerror;
    window.onerror = function(msg) { errs.push(msg); };
    return errs;
""")
print('Page errors:', errors)

driver.quit()
