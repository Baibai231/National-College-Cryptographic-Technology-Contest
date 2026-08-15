# v3 两轮全量回归对比

- 第一轮：`reports/sites/sites_latest.jsonl`
- 第二轮：`reports/archive/v3_runtime_audit_round1_20260815.jsonl`
- 总记录：302
- 完全一致：247
- 需要复核：55

| 网站 | 入口 | 状态 | 第一轮 | 第二轮 |
|---|---|---|---|---|
| 36kr.com | login | different | unknown / - / - | otp_only / code,phone / sms_code,verification_code |
| pan.baidu.com | login | different | unknown / - / - | human_blocked / - / captcha |
| segmentfault.com | signup | different | otp_only / code,phone / sms_code | otp_only / code,phone / sms_code,verification_code |
| www.163.com | signup | different | direct_password / password,phone / - | unknown / - / - |
| www.2345.com | login | different | unknown / - / - | otp_only / code,phone / sms_code,verification_code |
| www.3dmgame.com | login | different | direct_password / code,password,phone / sms_code | unknown / - / - |
| www.3dmgame.com | signup | different | direct_password / code,password,phone / sms_code | unknown / - / - |
| www.acfun.cn | login | different | direct_password / identifier,password / - | unknown / - / - |
| www.aliyun.com | login | different | direct_password / identifier,password / - | unknown / - / - |
| www.aliyun.com | signup | different | human_blocked / phone / sms_code,tos | unknown / - / - |
| www.anjuke.com | login | different | human_blocked / - / captcha | unknown / - / - |
| www.csdn.net | login | different | human_blocked / - / scan | sso_only / - / - |
| www.csdn.net | signup | different | human_blocked / - / scan | unknown / - / - |
| www.dianping.com | signup | different | unknown / - / - | human_blocked / - / captcha |
| www.dongchedi.com | login | different | otp_only / code,phone / sms_code | unknown / - / - |
| www.dongchedi.com | signup | different | otp_only / code,phone / sms_code | unknown / - / - |
| www.douban.com | login | different | human_blocked / code,phone / sms_code | unknown / - / - |
| www.douban.com | signup | different | human_blocked / code,phone / sms_code | unknown / - / - |
| www.douyu.com | signup | different | human_blocked / code,phone / captcha,sms_code | human_blocked / code,phone / captcha,sms_code |
| www.gamersky.com | signup | different | direct_password / password,phone / sms_code | unknown / - / - |
| www.goofish.com | login | different | human_blocked / code / verification_code | unknown / - / - |
| www.goofish.com | signup | different | human_blocked / code / verification_code | unknown / - / - |
| www.huaweicloud.com | login | different | human_blocked / - / captcha | human_blocked / code,phone / captcha,sms_code |
| www.hupu.com | login | different | human_blocked / code,identifier,phone / sms_code,tos | unknown / - / - |
| www.hupu.com | signup | different | human_blocked / code,identifier,phone / sms_code,tos | unknown / - / - |
| www.ikanchai.com | login | different | direct_password / identifier,password / - | unknown / - / - |
| www.jiemian.com | login | different | direct_password / code,identifier,password,phone / sms_code | unknown / - / - |
| www.jiemian.com | signup | different | otp_only / code,phone / sms_code | unknown / - / - |
| www.ke.com | login | different | direct_password / code,password,phone / sms_code | unknown / - / - |
| www.ke.com | signup | different | direct_password / code,password,phone / sms_code | unknown / - / - |
| www.lianjia.com | login | different | direct_password / code,password,phone / sms_code | unknown / - / - |
| www.lianjia.com | signup | different | direct_password / code,password,phone / sms_code | unknown / - / - |
| www.ly.com | login | different | direct_password / identifier,password / slide | unknown / - / - |
| www.ly.com | signup | different | direct_password / password,phone / slide | unknown / - / - |
| www.mafengwo.cn | signup | different | human_blocked / code,phone / sms_code,tos | unknown / - / - |
| www.pcauto.com.cn | login | different | human_blocked / code,identifier,phone / slide,sms_code,tos | unknown / - / - |
| www.pcauto.com.cn | signup | different | direct_password / password,phone / slide,sms_code,tos | unknown / - / - |
| www.people.com.cn | signup | different | direct_password / code,identifier,password,phone / sms_code,verification_code | unknown / code,identifier,password / verification_code |
| www.qyer.com | login | different | human_blocked / email / captcha | direct_password / code,email,identifier,password,phone / sms_code |
| www.taptap.cn | login | different | human_blocked / - / app_confirm | unknown / phone / - |
| www.taptap.cn | signup | different | human_blocked / - / app_confirm | human_blocked / - / app_confirm,captcha |
| www.toutiao.com | login | different | human_blocked / identifier,phone / sms_code | unknown / - / - |
| www.toutiao.com | signup | different | human_blocked / identifier,phone / sms_code | unknown / - / - |
| www.tuniu.com | login | different | direct_password / identifier,password / tos | unknown / - / - |
| www.tuniu.com | signup | different | human_blocked / code,phone / sms_code,tos | unknown / - / - |
| www.xiachufang.com | login | different | human_blocked / phone / slide,sms_code,tos | unknown / - / - |
| www.xiachufang.com | signup | different | human_blocked / phone / slide,sms_code,tos | unknown / - / - |
| www.xiaohongshu.com | login | different | human_blocked / code,phone / sms_code | unknown / - / - |
| www.xiaohongshu.com | signup | different | human_blocked / code,phone / sms_code | unknown / - / - |
| www.yiche.com | login | different | human_blocked / code,phone / sms_code,tos | unknown / - / - |
| www.yiche.com | signup | different | human_blocked / code,phone / sms_code,tos | unknown / - / - |
| www.youku.com | login | different | human_blocked / - / captcha,slide | human_blocked / - / tos |
| www.youku.com | signup | different | human_blocked / - / slide | human_blocked / - / captcha,slide |
| www.zhipin.com | login | different | otp_only / code,phone / sms_code | unknown / - / - |
| www.zhipin.com | signup | different | otp_only / code,phone / sms_code | unknown / - / - |
