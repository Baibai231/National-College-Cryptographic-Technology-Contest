# v3 两轮全量回归对比

- 第一轮：`reports/archive/v3_scan_sso_round1_20260814.jsonl`
- 第二轮：`reports/archive/v3_scan_sso_round2_20260814.jsonl`
- 总记录：302
- 完全一致：279
- 需要复核：23

| 网站 | 入口 | 状态 | 第一轮 | 第二轮 |
|---|---|---|---|---|
| 36kr.com | login | different | unknown / - / - | unknown / - / - |
| 36kr.com | signup | different | unknown / - / - | unknown / - / - |
| music.163.com | login | different | human_blocked / - / scan | None / - / - |
| music.163.com | signup | different | human_blocked / - / scan | None / - / - |
| pan.baidu.com | signup | different | direct_password / code,identifier,password / tos,verification_code | unknown / - / - |
| www.acfun.cn | signup | different | unknown / - / - | unknown / identifier,password / - |
| www.anjuke.com | signup | different | unknown / - / - | unknown / - / - |
| www.autohome.com.cn | login | different | human_blocked / - / scan | unknown / - / - |
| www.cnblogs.com | signup | different | direct_password / password,phone / - | direct_password / password,phone / captcha |
| www.ctrip.com | signup | different | multiple_methods / phone / - | otp_only / phone / sms_code |
| www.dianping.com | signup | different | unknown / - / - | human_blocked / - / slide |
| www.eastmoney.com | login | different | direct_password / code,email,password,phone / sms_code | human_blocked / - / captcha,slide |
| www.eastmoney.com | signup | different | unknown / - / - | unknown / code,phone / sms_code |
| www.fliggy.com | login | different | unknown / - / - | otp_only / phone / sms_code |
| www.huaweicloud.com | login | different | unknown / - / - | otp_only / code,phone / sms_code |
| www.huaweicloud.com | signup | different | direct_password / code,password,phone / sms_code | otp_only / code,phone / sms_code |
| www.iqiyi.com | login | different | unknown / - / - | unknown / - / - |
| www.mafengwo.cn | signup | different | unknown / - / - | human_blocked / code,phone / sms_code,tos |
| www.toutiao.com | login | different | human_blocked / identifier,phone / sms_code | otp_only / identifier,phone / sms_code |
| www.xiaohongshu.com | signup | different | human_blocked / code,phone / sms_code | otp_only / code,phone / sms_code |
| www.youku.com | login | different | human_blocked / - / tos | unknown / - / - |
| www.zhaopin.com | signup | different | human_blocked / code,phone / sms_code,tos | human_blocked / code,phone / sms_code,tos |
| www.zhipin.com | signup | different | unknown / - / - | otp_only / code,phone / sms_code |
