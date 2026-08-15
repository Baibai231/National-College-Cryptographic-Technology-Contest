# v3 两轮全量回归对比

- 第一轮：`reports/sites/sites_latest.jsonl`
- 第二轮：`reports/archive/v3_runtime_audit_candidate_20260815.jsonl`
- 总记录：302
- 完全一致：291
- 需要复核：11

| 网站 | 入口 | 状态 | 第一轮 | 第二轮 |
|---|---|---|---|---|
| 36kr.com | login | different | unknown / - / - | otp_only / code,phone / sms_code,verification_code |
| 36kr.com | signup | different | unknown / - / - | otp_only / code,phone / sms_code,verification_code |
| pan.baidu.com | login | different | unknown / - / - | human_blocked / - / captcha |
| www.2345.com | login | different | unknown / - / - | otp_only / code,phone / sms_code,verification_code |
| www.dianping.com | signup | different | unknown / - / - | human_blocked / - / captcha |
| www.douyu.com | signup | different | human_blocked / code,phone / captcha,sms_code | human_blocked / code,phone / captcha,sms_code |
| www.huaweicloud.com | login | different | human_blocked / - / captcha | human_blocked / code,phone / captcha,sms_code |
| www.qyer.com | login | different | human_blocked / email / captcha | direct_password / code,email,identifier,password,phone / sms_code |
| www.taptap.cn | signup | different | human_blocked / - / app_confirm | human_blocked / - / app_confirm,captcha |
| www.youku.com | login | different | human_blocked / - / captcha,slide | human_blocked / - / tos |
| www.youku.com | signup | different | human_blocked / - / slide | human_blocked / - / tos |
