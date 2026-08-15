# v3 两轮全量回归对比

- 第一轮：`reports/archive/v3_runtime_audit_round1_20260815.jsonl`
- 第二轮：`reports/archive/v3_runtime_audit_round2_20260815.jsonl`
- 总记录：302
- 完全一致：285
- 需要复核：17

| 网站 | 入口 | 状态 | 第一轮 | 第二轮 |
|---|---|---|---|---|
| 36kr.com | login | different | otp_only / code,phone / sms_code,verification_code | unknown / - / - |
| 36kr.com | signup | different | unknown / - / - | otp_only / code,phone / sms_code,verification_code |
| music.163.com | signup | different | human_blocked / - / scan | None / - / - |
| segmentfault.com | signup | different | otp_only / code,phone / sms_code,verification_code | unknown / code,phone / sms_code,verification_code |
| www.3dmgame.com | login | different | unknown / - / - | None / - / - |
| www.52pojie.cn | login | different | direct_password / email,identifier,password / - | unknown / - / - |
| www.cnblogs.com | login | different | direct_password / email,password / captcha | unknown / - / - |
| www.csdn.net | login | different | sso_only / - / - | human_blocked / - / scan |
| www.csdn.net | signup | different | unknown / - / - | human_blocked / - / scan |
| www.fliggy.com | signup | different | otp_only / phone / sms_code,verification_code | unknown / - / - |
| www.huya.com | signup | different | direct_password / code,password,phone / sms_code | direct_password / code,password,phone / sms_code |
| www.suning.com | login | different | direct_password / identifier,password / scan | unknown / - / - |
| www.suning.com | signup | different | human_blocked / - / scan | unknown / - / - |
| www.taptap.cn | signup | different | human_blocked / - / app_confirm,captcha | unknown / phone / - |
| www.toutiao.com | login | different | unknown / - / - | human_blocked / identifier,phone / captcha,sms_code |
| www.youku.com | login | different | human_blocked / - / tos | unknown / - / - |
| www.youku.com | signup | different | human_blocked / - / captcha,slide | human_blocked / - / slide |
