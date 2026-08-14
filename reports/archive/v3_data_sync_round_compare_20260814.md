# v3 两轮全量回归对比

- 第一轮：`reports/archive/v3_data_sync_round1_20260814.jsonl`
- 第二轮：`reports/archive/v3_data_sync_round2_20260814.jsonl`
- 总记录：302
- 完全一致：273
- 需要复核：29

| 网站 | 入口 | 状态 | 第一轮 | 第二轮 |
|---|---|---|---|---|
| 36kr.com | login | different | otp_only / code,phone / sms_code,verification_code | unknown / - / - |
| music.163.com | login | different | unknown / - / - | None / - / - |
| pan.baidu.com | login | different | human_blocked / - / captcha | unknown / - / - |
| www.2345.com | login | different | unknown / - / - | otp_only / code,phone / sms_code,verification_code |
| www.2345.com | signup | different | unknown / - / - | unknown / code,phone / sms_code,verification_code |
| www.52pojie.cn | login | different | unknown / - / - | direct_password / email,identifier,password / - |
| www.91.com | signup | different | unknown / - / - | email_only / identifier / - |
| www.aiqicha.com | login | different | human_blocked / - / captcha | unknown / - / - |
| www.anjuke.com | login | different | human_blocked / - / captcha | unknown / - / - |
| www.anjuke.com | signup | different | human_blocked / - / captcha | unknown / - / - |
| www.csdn.net | login | different | human_blocked / - / scan | sso_only / - / - |
| www.dianping.com | signup | different | unknown / - / - | human_blocked / - / captcha |
| www.douyin.com | login | different | human_blocked / - / captcha | human_blocked / - / - |
| www.douyin.com | signup | different | human_blocked / - / - | human_blocked / - / captcha |
| www.douyu.com | login | different | human_blocked / code,phone / captcha,sms_code | direct_password / code,password,phone / sms_code |
| www.douyu.com | signup | different | human_blocked / code,phone / captcha,sms_code | unknown / code,password,phone / captcha,sms_code |
| www.huaweicloud.com | login | different | human_blocked / code,phone / captcha,sms_code | human_blocked / - / captcha |
| www.iqiyi.com | login | different | unknown / - / - | unknown / - / - |
| www.qyer.com | login | different | human_blocked / email / captcha | direct_password / code,email,identifier,password,phone / sms_code |
| www.suning.com | login | different | unknown / - / - | direct_password / identifier,password / scan |
| www.suning.com | signup | different | unknown / - / - | human_blocked / - / scan |
| www.taptap.cn | login | different | human_blocked / - / app_confirm,captcha | unknown / phone / - |
| www.taptap.cn | signup | different | human_blocked / - / app_confirm,captcha | unknown / phone / - |
| www.toutiao.com | signup | different | unknown / - / - | human_blocked / identifier,phone / captcha,sms_code |
| www.ximalaya.com | login | different | unknown / - / - | unknown / - / - |
| www.youku.com | signup | different | human_blocked / - / captcha,slide | human_blocked / - / tos |
| www.zhipin.com | login | different | unknown / - / - | unknown / - / - |
| www.zhipin.com | signup | different | unknown / - / - | unknown / - / - |
| www.zol.com.cn | login | different | unknown / - / - | unknown / phone / - |
