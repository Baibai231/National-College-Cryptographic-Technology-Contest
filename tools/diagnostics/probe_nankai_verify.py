"""南开 iam 字段识别验证（修复后）。"""
import sys, time, json
sys.path.insert(0, '.')
from utils.util_test_password import _get_new_driver
from signup_flow_classifier.page_detector import (
    detect_fields_all_frames, detect_tabs_all_frames,
    classify_input_type)

site = sys.argv[1]
driver = _get_new_driver()
try:
    driver.get(site)
    time.sleep(6)
    print("URL:", driver.current_url[:70])
    print("fields:", detect_fields_all_frames(driver))
    print("tabs:", detect_tabs_all_frames(driver))
    els = driver.find_elements("css selector", "input")
    for el in els:
        try:
            if not el.is_displayed():
                continue
            print(f"  input id={el.get_attribute('id')!r:28} "
                  f"type={el.get_attribute('type')!r:10} "
                  f"-> classify={classify_input_type(el)}")
        except Exception:
            pass
finally:
    driver.quit()
