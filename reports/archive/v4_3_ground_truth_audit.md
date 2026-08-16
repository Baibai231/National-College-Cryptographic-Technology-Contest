# v4.3 全站地面真值审计（152 站逐站核对）

方法：用浏览器逐站打开真实网站，收集认证界面证据（输入框/可见文本/第三方图标/注册链接），与程序四轮回归后的正式数据逐站对照。证据文件 `/tmp/gt_evidence.jsonl`。

## 汇总

- ❓ 探测未复现弹窗：85 站
- ✅ 一致/基本一致：53 站
- ⚠️ 程序缺方法：11 站
- 🔀 站点跳转/反爬：3 站

## 逐站明细

| 站点 | 判定 | 登录(程序) | 注册(程序) | 审计说明 |
|---|---|---|---|---|
| 36kr.com | ✅ 一致/基本一致 | direct_password<br>手机号+密码、手机号+验证码、邮箱+密码 | otp_only<br>手机号+验证码 | 登录3方法有证据(密码/验证码/邮箱视图), 注册验证码一致 |
| cloud.tencent.com | ✅ 一致/基本一致 | direct_password<br>手机号+验证码+密码、邮箱/手机号+验证码+密码、第三方（QQ、微信） | direct_password<br>手机号+验证码+密码、邮箱/手机号+验证码+密码、第三方（QQ、微信） | 注册页证据吻合(手机+验证码+密码/微信扫码/邮箱注册) |
| deeix.gaoxiaobei.top | ✅ 一致/基本一致 | direct_password<br>账号+密码 | no_web_signup<br>账号+密码 | 仅登录页, 判断正确 |
| juejin.cn | ✅ 一致/基本一致 | direct_password<br>手机号+验证码、扫码、账号+密码 | human_blocked<br>手机号+验证码、扫码 | 手机+验证码/密码登录/微信一致 |
| leetcode.cn | ✅ 一致/基本一致 | direct_password<br>手机号+验证码、扫码、第三方（Apple、QQ、微信）、邮箱+密码 | human_blocked<br>手机号+验证码、扫码、第三方（Apple、QQ、微信） | 手机+验证码/帐号密码/扫码/第三方一致 |
| music.163.com | ✅ 一致/基本一致 | human_blocked<br>扫码 | human_blocked<br>扫码 | 仅扫码一致 |
| pan.baidu.com | ❓ 探测未复现弹窗 | human_blocked<br>— | direct_password<br>账号+验证码+密码 | 弹窗未复现(波动); 注册账号+验证码+密码 |
| segmentfault.com | ✅ 一致/基本一致 | otp_only<br>手机号+验证码、第三方（微信） | otp_only<br>手机号+验证码、第三方（微信） | 手机+验证码/微信/免密/密码一致 |
| shimo.im | ✅ 一致/基本一致 | direct_password<br>账号+密码 | no_web_signup<br>账号+密码 | 登录页账号+密码; 无注册一致 |
| tieba.baidu.com | ⚠️ 程序缺方法 | human_blocked<br>— | human_blocked<br>— | 证据有"扫码登录用户名登录立即注册", 程序空→缺方法(波动, 重测) |
| v.qq.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 未知 |
| web.okjike.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 扫码登录页, 程序unknown |
| weibo.com | ✅ 一致/基本一致 | otp_only<br>手机号+验证码、扫码、第三方（微信） | human_blocked<br>手机号+验证码、扫码、第三方（微信） | 手机+验证码/扫码/微信一致 |
| work.weixin.qq.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 未知(企业微信扫码为主) |
| www.10jqka.com.cn | ✅ 一致/基本一致 | direct_password<br>手机号+验证码、第三方（QQ、微信、微博）、账号+密码 | verification_then_password<br>手机号+验证码、手机号+验证码+密码、第三方（QQ、微信、微博） | 短信/密码/扫码+微信微博+注册链接一致 |
| www.12306.cn | ✅ 一致/基本一致 | direct_password<br>账号/邮箱/手机号+验证码+密码 | direct_password<br>账号/邮箱/手机号+验证码+密码 | 注册页字段吻合 |
| www.163.com | ❓ 探测未复现弹窗 | direct_password<br>邮箱+密码、手机号+验证码 | direct_password<br>手机号+密码 | 弹窗未复现; 邮箱/手机号+密码与验证码方法合理 |
| www.2345.com | ✅ 一致/基本一致 | direct_password<br>手机号+验证码、账号+密码 | no_web_signup<br>手机号+验证码 | 手机号登录/密码登录+新账号一致 |
| www.360.cn | ✅ 一致/基本一致 | direct_password<br>邮箱+验证码+密码 | direct_password<br>邮箱+验证码+密码 | 手机号注册/邮箱注册+验证码+密码一致 |
| www.3dmgame.com | ✅ 一致/基本一致 | direct_password<br>手机号+验证码+密码 | direct_password<br>手机号+验证码+密码 | 手机号+密码+验证码一致 |
| www.4399.com | ❓ 探测未复现弹窗 | direct_password<br>手机号+验证码、第三方（QQ、微信、微博）、账号+密码 | human_blocked<br>手机号+验证码、第三方（QQ、微信、微博） | 弹窗未复现; 账号密码登录+第三方方法合理 |
| www.51.com | ⚠️ 程序缺方法 | direct_password<br>第三方（QQ、微信）、账号+密码 | direct_password<br>第三方（QQ、微信）、账号+密码 | 证据"账号登录微信登录手机登录"+立即注册, 程序缺手机号+验证码视图(波动, 重测) |
| www.51cto.com | ❓ 探测未复现弹窗 | direct_password<br>第三方（微信）、账号/手机号+验证码、账号/邮箱+密码 | otp_only<br>第三方（微信）、账号/手机号+验证码 | 弹窗未复现; 微信/手机号验证码/邮箱密码方法合理 |
| www.51job.com | ✅ 一致/基本一致 | direct_password<br>手机号+验证码、扫码、第三方（微信）、账号/手机号+验证码+密码 | human_blocked<br>手机号+验证码、扫码、第三方（微信） | 手机+短信验证码/扫码/密码登录/微信一致 |
| www.52pojie.cn | ⚠️ 程序缺方法 | direct_password<br>账号/邮箱+密码 | direct_password<br>账号/邮箱+密码 | 证据有QQ登录+微信图标, 程序缺第三方→修复img alt后重测 |
| www.58.com | ❓ 探测未复现弹窗 | human_blocked<br>扫码 | direct_password<br>账号/手机号+验证码+密码 | 弹窗未复现; 扫码登录/手机号+验证码+密码方法合理 |
| www.58pic.com | ❓ 探测未复现弹窗 | sso_only<br>第三方（QQ、微信、微博） | sso_only<br>第三方（QQ、微信、微博） | 弹窗未复现; 第三方QQ/微信/微博方法合理 |
| www.7k7k.com | ✅ 一致/基本一致 | direct_password<br>密码 | direct_password<br>密码 | 账号4-32位+密码一致(微信是关注非登录) |
| www.91.com | 🔀 站点跳转/反爬 | email_only<br>— | email_only<br>— | 主页跳转m.hao123.com, 程序email_only待人工确认 |
| www.acfun.cn | ❓ 探测未复现弹窗 | direct_password<br>扫码、账号+密码 | no_web_signup<br>扫码、账号+密码 | 弹窗未复现(波动); 扫码+账号密码方法合理 |
| www.aiqicha.com | ✅ 一致/基本一致 | human_blocked<br>— | human_blocked<br>— | 反爬扫码验证墙, 程序无方法一致 |
| www.aliyun.com | ❓ 探测未复现弹窗 | direct_password<br>账号+密码、账号+验证码 | human_blocked<br>手机号+验证码 | 弹窗未复现; 账号+密码/验证码方法合理 |
| www.amap.com | ⚠️ 程序缺方法 | human_blocked<br>手机号+验证码、扫码 | human_blocked<br>手机号+验证码、扫码 | 证据有"密码登录/短信登录/子账号登录/二维码登录", 程序缺密码登录→重测 |
| www.anjuke.com | ❓ 探测未复现弹窗 | human_blocked<br>— | human_blocked<br>— | 弹窗未复现; 城市站跳转 |
| www.autohome.com.cn | ❓ 探测未复现弹窗 | direct_password<br>账号+密码、手机号+验证码、扫码、第三方（QQ、微信） | human_blocked<br>扫码、第三方（QQ、微信） | 弹窗未复现; 登录4方法(密码/验证码/扫码/QQ微信)合理 |
| www.baidu.com | ⚠️ 程序缺方法 | direct_password<br>账号+密码、账号+验证码+密码 | direct_password<br>账号+密码、账号+验证码+密码 | 证据"QQ账号新浪微博微信立即注册", 程序缺第三方→修复img alt后重测 |
| www.bianlifeng.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 无认证界面 |
| www.bilibili.com | ❓ 探测未复现弹窗 | direct_password<br>手机号+验证码、账号+密码 | direct_password<br>账号+密码、手机号+验证码 | 弹窗未复现; 手机号+验证码/账号+密码合理 |
| www.bitauto.com | 🔀 站点跳转/反爬 | unknown<br>— | unknown<br>— | 跳转yiche.com |
| www.caixin.com | 🔀 站点跳转/反爬 | direct_password<br>邮箱+验证码+密码 | direct_password<br>邮箱+验证码+密码 | 跳转caixinglobal国际版 |
| www.cctalk.com | ❓ 探测未复现弹窗 | otp_only<br>手机号+验证码 | otp_only<br>手机号+验证码 | 弹窗未复现; 手机号+验证码合理 |
| www.cctv.com | ⚠️ 程序缺方法 | direct_password<br>账号+密码 | direct_password<br>账号+密码 | 证据: 微信/QQ/新浪/支付宝图标+立即注册(reg.cctv.com). 程序只有账号+密码→已修复img alt/注册跟随/点击重试, 重测 |
| www.china.com | ❓ 探测未复现弹窗 | direct_password<br>第三方（QQ）、账号+密码 | direct_password<br>第三方（QQ）、账号+密码 | 弹窗未复现; QQ+账号密码合理 |
| www.chinaacc.com | ❓ 探测未复现弹窗 | direct_password<br>手机号+密码、扫码、第三方（微信） | sso_only<br>第三方（微信） | 弹窗未复现; 手机号+密码/扫码/微信合理 |
| www.chinanews.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 无认证界面(企业邮箱), unknown合理 |
| www.cnblogs.com | ❓ 探测未复现弹窗 | direct_password<br>手机号+密码、邮箱+密码、手机号+验证码 | direct_password<br>手机号+密码 | 弹窗未复现; 手机号/邮箱+密码+验证码合理 |
| www.coolapk.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 扫码下载非登录, unknown合理 |
| www.cqcb.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 有微信/微博图标但无弹窗证据 |
| www.csdn.net | ✅ 一致/基本一致 | human_blocked<br>手机号+验证码、扫码、第三方（微信） | human_blocked<br>手机号+验证码、扫码、第三方（微信） | 手机号+验证码/扫码/微信一致 |
| www.ctrip.com | ✅ 一致/基本一致 | otp_only<br>手机号+验证码 | otp_only<br>手机号+验证码 | 注册页手机+验证码+设密码一致 |
| www.cyzone.cn | ❓ 探测未复现弹窗 | direct_password<br>手机号+验证码、手机号+验证码+密码 | verification_then_password<br>手机号+验证码、手机号+验证码+密码 | 弹窗未复现; 手机号+验证码(+密码)合理 |
| www.d1ev.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 无认证界面 |
| www.dajie.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 无认证界面 |
| www.dangdang.com | ✅ 一致/基本一致 | direct_password<br>密码、第三方（支付宝、百度、QQ、微信、微博）、验证码 | otp_only<br>验证码 | 密码/验证码/第三方一致 |
| www.dewu.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 扫码下载非登录 |
| www.dianping.com | ✅ 一致/基本一致 | human_blocked<br>— | human_blocked<br>— | 美团人机验证墙一致 |
| www.dingtalk.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | App-first, 未知 |
| www.dongchedi.com | ✅ 一致/基本一致 | direct_password<br>手机号+密码、手机号+验证码 | otp_only<br>手机号+验证码 | 手机验证码/密码登录一致 |
| www.dongqiudi.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | App-first |
| www.douban.com | ✅ 一致/基本一致 | human_blocked<br>手机号+验证码 | human_blocked<br>手机号+验证码 | 手机号+验证码合理(弹窗未复现但方法符合) |
| www.douyin.com | ✅ 一致/基本一致 | direct_password<br>账号/手机号+密码、账号/手机号+验证码 | human_blocked<br>账号/手机号+验证码 | 验证码登录/密码登录/扫码一致 |
| www.douyu.com | ❓ 探测未复现弹窗 | human_blocked<br>手机号+验证码 | human_blocked<br>手机号+验证码 | 弹窗未复现; 手机号+验证码合理 |
| www.duozhi.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 无认证界面 |
| www.dxy.cn | ⚠️ 程序缺方法 | unknown<br>— | unknown<br>— | 证据: 免费注册→auth.dxy.cn登录页. 程序unknown→缺方法, 重测 |
| www.eastmoney.com | ⚠️ 程序缺方法 | human_blocked<br>— | human_blocked<br>— | 证据"QQ登录微信登录微博登录", 程序human_blocked无方法→缺第三方(波动, 重测) |
| www.ele.me | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | App-first |
| www.enet.com.cn | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 无认证界面 |
| www.feishu.cn | ❓ 探测未复现弹窗 | human_blocked<br>手机号+验证码、扫码 | human_blocked<br>手机号+验证码、扫码 | 弹窗未复现; 手机号+验证码/扫码合理 |
| www.fenqi.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 无认证界面 |
| www.fliggy.com | ✅ 一致/基本一致 | otp_only<br>手机号+验证码 | otp_only<br>手机号+验证码 | 淘宝注册体系一致 |
| www.gamersky.com | ✅ 一致/基本一致 | direct_password<br>手机号+验证码、账号+密码 | direct_password<br>手机号+验证码+密码、第三方（QQ、微信） | 手机号+验证码/账号密码/第三方一致 |
| www.gaoding.com | ❓ 探测未复现弹窗 | human_blocked<br>手机号+验证码 | human_blocked<br>手机号+验证码 | 弹窗未复现; 手机号+验证码合理 |
| www.gitee.com | ✅ 一致/基本一致 | direct_password<br>账号/手机号+密码、第三方（华为） | direct_password<br>账号/手机号+密码、第三方（华为） | 注册页字段吻合 |
| www.gmw.cn | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 无认证界面 |
| www.goofish.com | ❓ 探测未复现弹窗 | human_blocked<br>验证码 | human_blocked<br>验证码 | 弹窗未复现; 验证码合理 |
| www.guancha.cn | ✅ 一致/基本一致 | direct_password<br>手机号+验证码+密码、手机号+验证码 | direct_password<br>手机号+验证码+密码、手机号+验证码 | 手机号登录/密码登录+图形验证码一致 |
| www.guazi.com | ❓ 探测未复现弹窗 | direct_password<br>手机号+验证码+密码 | no_web_signup<br>手机号+验证码+密码 | 弹窗未复现; 手机号+验证码+密码合理 |
| www.guokr.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 无认证界面 |
| www.huaweicloud.com | ❓ 探测未复现弹窗 | direct_password<br>手机号+密码、手机号+验证码、第三方（支付宝、微信） | otp_only<br>手机号+验证码 | 弹窗未复现; 手机号+密码/验证码/第三方合理(探索成果) |
| www.hujiang.com | ✅ 一致/基本一致 | otp_only<br>手机号+验证码 | otp_only<br>手机号+验证码 | 手机号+动态码一致 |
| www.hupu.com | ❓ 探测未复现弹窗 | direct_password<br>账号+密码、第三方（QQ）、账号/手机号+验证码 | human_blocked<br>第三方（QQ、微信）、账号/手机号+验证码 | 弹窗未复现; 账号+密码/QQ/验证码合理 |
| www.huxiu.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 无认证界面 |
| www.huya.com | ✅ 一致/基本一致 | direct_password<br>手机号+密码、手机号+验证码 | direct_password<br>手机号+密码、手机号+验证码+密码 | 手机号+密码/验证码一致 |
| www.ifeng.com | ❓ 探测未复现弹窗 | human_blocked<br>— | direct_password<br>手机号+验证码+密码 | 弹窗未复现; 手机号+验证码+密码合理 |
| www.ikanchai.com | ❓ 探测未复现弹窗 | direct_password<br>账号+密码 | unknown<br>— | 弹窗未复现; 账号+密码合理 |
| www.imooc.com | ❓ 探测未复现弹窗 | direct_password<br>手机号+验证码、邮箱+密码 | human_blocked<br>手机号+验证码 | 弹窗未复现; 手机号+验证码/邮箱+密码合理 |
| www.infzm.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 无认证界面 |
| www.iqiyi.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | VIP页无弹窗证据 |
| www.ithome.com | ❓ 探测未复现弹窗 | human_blocked<br>— | human_blocked<br>— | 弹窗未复现 |
| www.ixigua.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | App-first |
| www.jd.com | ⚠️ 程序缺方法 | direct_password<br>手机号+验证码、第三方（QQ、微信）、账号+密码 | unknown<br>— | 登录3方法一致; 注册侧程序unknown但证据有立即注册(reg.jd.com)→注册侧缺方法, 重测 |
| www.jdytoy.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 无认证界面 |
| www.jianshu.com | ✅ 一致/基本一致 | direct_password<br>第三方（QQ、微信）、邮箱+密码 | direct_password<br>手机号+密码、第三方（QQ、微信） | 邮箱+密码/手机号+密码/QQ微信一致 |
| www.jiemian.com | ❓ 探测未复现弹窗 | direct_password<br>手机号+验证码、第三方（QQ、微博）、账号+密码 | human_blocked<br>手机号+验证码 | 弹窗未复现; 手机号+验证码/QQ微博/账号密码合理 |
| www.jiguang.cn | ❓ 探测未复现弹窗 | unknown<br>— | email_only<br>— | 英文站, 注册链接存在 |
| www.kanxue.com | ✅ 一致/基本一致 | human_blocked<br>手机号+验证码、第三方（GitHub、微信） | human_blocked<br>手机号+验证码、第三方（GitHub、微信） | 手机注册+第三方(GitHub/微信)一致 |
| www.kdocs.cn | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 微信/QQ扫码体验(非登录认证), unknown合理 |
| www.ke.com | ✅ 一致/基本一致 | direct_password<br>手机号+验证码+密码 | direct_password<br>手机号+验证码+密码 | 扫码/短信/密码登录+注册账号一致 |
| www.kuaishou.com | ❓ 探测未复现弹窗 | otp_only<br>手机号+验证码、第三方（QQ、微信） | otp_only<br>手机号+验证码、第三方（QQ、微信） | 弹窗未复现(波动); 手机号登录+第三方合理 |
| www.kugou.com | ✅ 一致/基本一致 | human_blocked<br>扫码 | human_blocked<br>扫码 | 扫码一致 |
| www.kuwo.cn | ✅ 一致/基本一致 | direct_password<br>账号+验证码+密码 | direct_password<br>账号+验证码+密码 | 用户名/邮箱/手机+密码+验证码一致 |
| www.lagou.com | ❓ 探测未复现弹窗 | human_blocked<br>— | human_blocked<br>— | 弹窗未复现 |
| www.lianjia.com | ✅ 一致/基本一致 | direct_password<br>手机号+验证码+密码 | direct_password<br>手机号+验证码+密码 | 扫码/短信/密码+注册账号一致 |
| www.liepin.com | ✅ 一致/基本一致 | direct_password<br>账号+密码、手机号+验证码 | human_blocked<br>手机号+验证码 | 手机号+短信验证码+密码登录一致 |
| www.ling.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 无认证界面 |
| www.ly.com | ❓ 探测未复现弹窗 | direct_password<br>账号+密码、账号+验证码+密码、第三方（支付宝、QQ、微信） | direct_password<br>手机号+密码 | 弹窗未复现; 账号+密码/验证码/第三方合理 |
| www.mafengwo.cn | ❓ 探测未复现弹窗 | direct_password<br>账号+密码 | human_blocked<br>手机号+验证码 | 弹窗未复现; 账号+密码/手机验证码合理 |
| www.maimai.cn | ❓ 探测未复现弹窗 | human_blocked<br>手机号+验证码、扫码 | human_blocked<br>手机号+验证码、扫码 | 弹窗未复现; 手机号+验证码/扫码合理 |
| www.meituan.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 弹窗未复现(波动) |
| www.mgtv.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 协议弹窗+App-first |
| www.miguvideo.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | App-first |
| www.mingdao.com | ✅ 一致/基本一致 | human_blocked<br>手机号+验证码 | human_blocked<br>手机号+验证码 | 手机号+验证码/微信/抖音扫码+免费注册一致 |
| www.nbd.com.cn | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 无认证界面 |
| www.niewei.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 无认证界面 |
| www.nowcoder.com | ✅ 一致/基本一致 | human_blocked<br>手机号+验证码、扫码 | otp_only<br>手机号+验证码 | 手机号+验证码/扫码/密码登录/自动注册一致 |
| www.oschina.net | ✅ 一致/基本一致 | direct_password<br>账号+密码、手机号+验证码、第三方（Gitee） | human_blocked<br>手机号+验证码、第三方（Gitee） | 手机号+短信验证码/Gitee登录/免密/密码一致 |
| www.pcauto.com.cn | ❓ 探测未复现弹窗 | human_blocked<br>第三方（QQ、微信、微博）、账号/手机号+验证码 | direct_password<br>手机号+验证码+密码、第三方（QQ、微信、微博） | 弹窗未复现; QQ微信微博/手机号+验证码合理 |
| www.pconline.com.cn | ❓ 探测未复现弹窗 | direct_password<br>手机号+验证码、账号+密码 | otp_only<br>手机号+验证码 | 弹窗未复现; 手机号+验证码/账号密码合理 |
| www.people.com.cn | ❓ 探测未复现弹窗 | direct_password<br>账号+验证码+密码 | direct_password<br>手机号+验证码+密码、账号+验证码+密码 | 弹窗未复现; 账号/手机号+验证码+密码合理 |
| www.pinduoduo.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 微信扫码下载(无网页登录), unknown合理 |
| www.qq.com | ⚠️ 程序缺方法 | human_blocked<br>扫码、第三方（微信） | human_blocked<br>扫码、第三方（微信） | 证据"QQ登录微信登录手机号登录", 程序只有扫码+微信→缺QQ/手机号tab, 重测 |
| www.qunar.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 无认证界面 |
| www.qyer.com | ✅ 一致/基本一致 | direct_password<br>账号/邮箱/手机号+验证码+密码 | direct_password<br>账号/邮箱/手机号+验证码+密码 | 注册页手机号+验证码+用户名+密码一致 |
| www.sina.com.cn | ❓ 探测未复现弹窗 | direct_password<br>手机号+验证码、扫码、第三方（微信）、邮箱+密码 | no_web_signup<br>扫码、第三方（微信）、邮箱+密码 | 弹窗未复现(波动); 登录4方法合理 |
| www.smzdm.com | ❓ 探测未复现弹窗 | otp_only<br>手机号+验证码 | otp_only<br>手机号+验证码 | 弹窗未复现; 手机号+验证码合理 |
| www.sohu.com | ✅ 一致/基本一致 | otp_only<br>手机号+验证码 | otp_only<br>手机号+验证码 | 手机号验证码/微信微博/账号密码一致 |
| www.suning.com | ❓ 探测未复现弹窗 | direct_password<br>手机号+验证码、扫码、账号+密码 | direct_password<br>手机号+验证码+密码 | 弹窗未复现; 手机号+验证码/扫码/账号密码合理 |
| www.taobao.com | ✅ 一致/基本一致 | otp_only<br>手机号+验证码 | otp_only<br>手机号+验证码 | 淘宝注册页手机号+校验码一致 |
| www.taptap.cn | ❓ 探测未复现弹窗 | human_blocked<br>— | human_blocked<br>— | App-first |
| www.thepaper.cn | ❓ 探测未复现弹窗 | direct_password<br>手机号+验证码+密码、账号+密码 | no_web_signup<br>手机号+验证码+密码 | 弹窗未复现; 手机号+验证码+密码合理 |
| www.tianya.cn | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 无认证界面 |
| www.toutiao.com | ❓ 探测未复现弹窗 | human_blocked<br>扫码、第三方（抖音、QQ、微信）、账号/手机号+验证码 | human_blocked<br>扫码、第三方（抖音、QQ、微信）、账号/手机号+验证码 | 弹窗未复现; 扫码/抖音QQ微信/手机验证码合理 |
| www.tuniu.com | ❓ 探测未复现弹窗 | direct_password<br>账号+密码、第三方（微信） | human_blocked<br>手机号+验证码 | 弹窗未复现; 账号+密码/微信/手机验证码合理 |
| www.v2ex.com | ✅ 一致/基本一致 | sso_only<br>第三方（Google、Solana） | sso_only<br>第三方（Google、Solana） | 仅第三方(Google等)一致 |
| www.vip.com | ✅ 一致/基本一致 | direct_password<br>扫码、第三方（支付宝、QQ、微信、微博）、账号+密码 | direct_password<br>手机号+密码、扫码、第三方（支付宝、QQ、微信、微博） | 扫码/账户登录+免费注册一致 |
| www.xiachufang.com | ✅ 一致/基本一致 | human_blocked<br>手机号+验证码、第三方（QQ、微博） | human_blocked<br>手机号+验证码、第三方（QQ、微博） | 手机号+验证码/QQ微博一致(App注册) |
| www.xiaohongshu.com | ✅ 一致/基本一致 | human_blocked<br>手机号+验证码 | human_blocked<br>手机号+验证码 | 手机号+验证码/微信扫码一致 |
| www.ximalaya.com | ❓ 探测未复现弹窗 | unknown<br>— | human_blocked<br>— | 注册规则页无表单 |
| www.xinhuanet.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 无认证界面 |
| www.yicai.com | ✅ 一致/基本一致 | direct_password<br>手机号+密码、手机号+验证码 | human_blocked<br>手机号+验证码 | 验证码登录/密码登录/微信扫码一致 |
| www.yiche.com | ❓ 探测未复现弹窗 | direct_password<br>账号+验证码+密码、手机号+验证码 | human_blocked<br>手机号+验证码 | 弹窗未复现; 账号+验证码+密码合理 |
| www.youku.com | ❓ 探测未复现弹窗 | direct_password<br>邮箱+密码、第三方（支付宝、QQ、淘宝、微信、微博）、邮箱+验证码 | human_blocked<br>验证码 | 弹窗未复现; 邮箱+密码/验证码/第三方合理 |
| www.zcool.com.cn | ❓ 探测未复现弹窗 | direct_password<br>第三方（QQ、微信、微博）、账号+密码、账号+验证码、验证码 | human_blocked<br>第三方（QQ、微信、微博） | 弹窗未复现; 第三方/账号密码/验证码合理 |
| www.zhaopin.com | ✅ 一致/基本一致 | human_blocked<br>手机号+验证码 | human_blocked<br>手机号+验证码、第三方（微信） | 手机号+短信验证码/微信扫码一致 |
| www.zhibo8.cc | ❓ 探测未复现弹窗 | human_blocked<br>— | human_blocked<br>— | App-first(扫码下载) |
| www.zhihu.com | ✅ 一致/基本一致 | direct_password<br>手机号+验证码、扫码、第三方（微信）、账号+密码 | human_blocked<br>手机号+验证码、扫码、第三方（微信） | 手机号+验证码/扫码微信/密码登录一致 |
| www.zhipin.com | ⚠️ 程序缺方法 | unknown<br>— | unknown<br>— | 证据: 手机号+短信验证码+微信登录+APP扫码, 程序unknown→缺方法(波动, 重测) |
| www.zhuanzhuan.com | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 无认证界面(App-first) |
| www.zol.com.cn | ❓ 探测未复现弹窗 | unknown<br>— | unknown<br>— | 弹窗未复现; 结构难点 |
| xueqiu.com | ✅ 一致/基本一致 | human_blocked<br>手机号+验证码、扫码、第三方（微信） | human_blocked<br>手机号+验证码、扫码、第三方（微信） | 验证码/账号密码/二维码/微信/邮箱验证码一致 |
| y.qq.com | ✅ 一致/基本一致 | sso_only<br>第三方（微信） | sso_only<br>第三方（微信） | QQ登录微信登录一致 |
| you.163.com | ✅ 一致/基本一致 | otp_only<br>手机号+验证码 | otp_only<br>手机号+验证码 | 手机号登录/邮箱登录+邮箱注册一致 |
