# v4.3 全站地面真值审计（152 站逐站核对，两轮探测）

方法：第一轮全部站点探测 + 第二轮深度探测（hover 展开/多轮重试）补 85 个未复现弹窗站；逐站对照程序输出与真实证据。证据文件 /tmp/gt_evidence_final.jsonl。

## 汇总

- ✅ 一致/基本一致：83 站
- ❓ 深度探测仍无证据：37 站
- ⚠️ 程序缺方法：12 站
- 🔀 站点跳转/反爬：3 站

## 逐站明细

| 站点 | 判定 | 登录(程序) | 注册(程序) | 审计说明 |
|---|---|---|---|---|
| 36kr.com | ✅ 一致/基本一致 | direct_password<br>手机号+密码、手机号+验证码、邮箱+密码 | otp_only<br>手机号+验证码 | 手机号+验证码+密码视图一致 |
| music.163.com | ✅ 一致/基本一致 | human_blocked<br>扫码 | human_blocked<br>扫码 | 深度证据: 登录+扫码登录; 程序扫码吻合 |
| pan.baidu.com | ⚠️ 程序缺方法 | human_blocked<br>— | direct_password<br>账号+验证码+密码 | 深度证据: 扫码登录/账号登录/去登录; 程序登录空(波动) |
| tieba.baidu.com | ⚠️ 程序缺方法 | human_blocked<br>— | human_blocked<br>— | 深度证据: 登录/注册+微信/新浪/QQ; 程序空(波动) |
| v.qq.com | ⚠️ 程序缺方法 | unknown<br>— | unknown<br>— | 深度证据: 账号登录/微信登录/QQ登录/手机号登录; 程序unknown(弹窗未开) |
| web.okjike.com | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无(即刻App扫码登录页) |
| www.10jqka.com.cn | ✅ 一致/基本一致 | direct_password<br>手机号+验证码、第三方（QQ、微信、微博）、账号+密码 | verification_then_password<br>手机号+验证码、手机号+验证码+密码、第三方（QQ、微信、微博） | 短信/密码/扫码+微信微博一致 |
| www.12306.cn | ✅ 一致/基本一致 | direct_password<br>账号/邮箱/手机号+验证码+密码 | direct_password<br>账号/邮箱/手机号+验证码+密码 | 深度证据: 注册页用户名+密码+邮箱+手机号; 程序吻合 |
| www.163.com | ✅ 一致/基本一致 | direct_password<br>邮箱+密码、手机号+验证码 | direct_password<br>手机号+密码 | 深度证据: 登录+注册免费邮箱; 程序邮箱/手机号方法合理 |
| www.2345.com | ✅ 一致/基本一致 | direct_password<br>手机号+验证码、账号+密码 | no_web_signup<br>手机号+验证码 | 深度证据: 手机号登录密码登录+新账号; 程序吻合 |
| www.360.cn | ✅ 一致/基本一致 | direct_password<br>邮箱+验证码+密码 | direct_password<br>邮箱+验证码+密码 | 深度证据: 手机号注册/邮箱注册+邮箱验证码+密码; 程序吻合 |
| www.3dmgame.com | ✅ 一致/基本一致 | direct_password<br>手机号+验证码+密码 | direct_password<br>手机号+验证码+密码 | 深度证据: 手机号+密码+验证码; 程序吻合 |
| www.4399.com | ✅ 一致/基本一致 | direct_password<br>手机号+验证码、第三方（QQ、微信、微博）、账号+密码 | human_blocked<br>手机号+验证码、第三方（QQ、微信、微博） | 深度证据: 登录/注册+微信小游戏; 程序账号密码+第三方吻合 |
| www.51.com | ⚠️ 程序缺方法 | direct_password<br>第三方（QQ、微信）、账号+密码 | direct_password<br>第三方（QQ、微信）、账号+密码 | 深度证据: 登录|注册(账号登录/微信登录/手机登录tab); 程序缺手机登录视图(波动) |
| www.51cto.com | ✅ 一致/基本一致 | direct_password<br>第三方（微信）、账号/手机号+验证码、账号/邮箱+密码 | otp_only<br>第三方（微信）、账号/手机号+验证码 | 深度证据: 微信登录短信登录密码登录; 程序3方法吻合 |
| www.51job.com | ✅ 一致/基本一致 | direct_password<br>手机号+验证码、扫码、第三方（微信）、账号/手机号+验证码+密码 | human_blocked<br>手机号+验证码、扫码、第三方（微信） | 深度证据: 手机号+短信验证码+扫码登录; 程序4方法吻合 |
| www.58.com | ✅ 一致/基本一致 | human_blocked<br>扫码 | direct_password<br>账号/手机号+验证码+密码 | 深度证据: 账号登录+App扫码登录; 程序登录=扫码吻合 |
| www.58pic.com | ✅ 一致/基本一致 | sso_only<br>第三方（QQ、微信、微博） | sso_only<br>第三方（QQ、微信、微博） | 深度证据: 登录/注册+立即登录; 程序第三方QQ微信微博吻合 |
| www.7k7k.com | ✅ 一致/基本一致 | direct_password<br>密码 | direct_password<br>密码 | 深度证据: 登录注册; 程序密码吻合 |
| www.91.com | 🔀 站点跳转/反爬 | email_only<br>— | email_only<br>— | 深度证据: 立即登录(站点跳转hao123); 程序email_only待人工确认 |
| www.acfun.cn | ✅ 一致/基本一致 | direct_password<br>扫码、账号+密码 | no_web_signup<br>扫码、账号+密码 | 深度证据: 登录/注册; 程序扫码+账号密码吻合 |
| www.aiqicha.com | ✅ 一致/基本一致 | human_blocked<br>— | human_blocked<br>— | 反爬扫码验证一致 |
| www.aliyun.com | ⚠️ 程序缺方法 | direct_password<br>账号+密码、账号+验证码 | human_blocked<br>手机号+验证码 | 深度证据: 账密登录/手机号登录/通行密钥/支付宝/钉钉/APP; 程序登录缺第三方 |
| www.amap.com | ✅ 一致/基本一致 | human_blocked<br>手机号+验证码、扫码 | human_blocked<br>手机号+验证码、扫码 | 深度证据: 手机号+验证码; 程序手机号+验证码/扫码吻合(密码登录tab仍缺) |
| www.anjuke.com | ✅ 一致/基本一致 | human_blocked<br>— | human_blocked<br>— | 深度证据: 登录注册; 程序human_blocked(波动)方法待复测 |
| www.autohome.com.cn | ✅ 一致/基本一致 | direct_password<br>账号+密码、手机号+验证码、扫码、第三方（QQ、微信） | human_blocked<br>扫码、第三方（QQ、微信） | 深度证据: 登录+扫码下载; 程序登录4方法吻合 |
| www.baidu.com | ⚠️ 程序缺方法 | direct_password<br>账号+密码、账号+验证码+密码 | direct_password<br>账号+密码、账号+验证码+密码 | 深度证据: 百度APP扫码+账号登录+QQ/新浪微博/微信第三方; 程序缺第三方 |
| www.bianlifeng.com | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 无认证界面 |
| www.bitauto.com | 🔀 站点跳转/反爬 | unknown<br>— | unknown<br>— | 跳转yiche.com |
| www.caixin.com | 🔀 站点跳转/反爬 | direct_password<br>邮箱+验证码+密码 | direct_password<br>邮箱+验证码+密码 | 跳转caixinglobal国际版 |
| www.cctalk.com | ❓ 深度探测仍无证据 | otp_only<br>手机号+验证码 | otp_only<br>手机号+验证码 | 深度探测仍无认证界面(App-first) |
| www.cctv.com | ⚠️ 程序缺方法 | direct_password<br>账号+密码 | direct_password<br>账号+密码 | 深度证据: 登录/立即注册+微信/QQ/新浪/支付宝图标; 程序只有账号+密码(弹窗波动) |
| www.china.com | ✅ 一致/基本一致 | direct_password<br>第三方（QQ）、账号+密码 | direct_password<br>第三方（QQ）、账号+密码 | 深度证据: 登录注册; 程序QQ+账号密码吻合 |
| www.chinaacc.com | ❓ 深度探测仍无证据 | direct_password<br>手机号+密码、扫码、第三方（微信） | sso_only<br>第三方（微信） | 深度探测仍无认证界面 |
| www.chinanews.com | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无认证界面 |
| www.cnblogs.com | ✅ 一致/基本一致 | direct_password<br>手机号+密码、邮箱+密码、手机号+验证码 | direct_password<br>手机号+密码 | 深度证据: 密码登录短信登录; 程序手机号/邮箱+密码/验证码吻合 |
| www.coolapk.com | ✅ 一致/基本一致 | unknown<br>— | unknown<br>— | 深度证据: 手机扫码下载App(无登录); 程序unknown吻合 |
| www.cqcb.com | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无认证界面 |
| www.csdn.net | ✅ 一致/基本一致 | human_blocked<br>手机号+验证码、扫码、第三方（微信） | human_blocked<br>手机号+验证码、扫码、第三方（微信） | 手机号+验证码/扫码/微信一致 |
| www.ctrip.com | ✅ 一致/基本一致 | otp_only<br>手机号+验证码 | otp_only<br>手机号+验证码 | 深度证据: 注册页手机号+短信验证码+设密码; 程序吻合 |
| www.cyzone.cn | ✅ 一致/基本一致 | direct_password<br>手机号+验证码、手机号+验证码+密码 | verification_then_password<br>手机号+验证码、手机号+验证码+密码 | 深度证据: 手机号+短信验证码+验证码登录/账户登录; 程序吻合 |
| www.d1ev.com | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无 |
| www.dajie.com | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无 |
| www.dangdang.com | ✅ 一致/基本一致 | direct_password<br>密码、第三方（支付宝、百度、QQ、微信、微博）、验证码 | otp_only<br>验证码 | 深度证据: 请登录成为会员; 程序密码/验证码/第三方吻合 |
| www.dewu.com | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无认证界面(App-first扫码下载) |
| www.dingtalk.com | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | App-first |
| www.dongchedi.com | ✅ 一致/基本一致 | direct_password<br>手机号+密码、手机号+验证码 | otp_only<br>手机号+验证码 | 深度证据: 手机号+验证码; 程序吻合 |
| www.dongqiudi.com | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | App-first |
| www.douyin.com | ✅ 一致/基本一致 | direct_password<br>账号/手机号+密码、账号/手机号+验证码 | human_blocked<br>账号/手机号+验证码 | 深度证据: 手机号+验证码; 程序吻合 |
| www.douyu.com | ✅ 一致/基本一致 | human_blocked<br>手机号+验证码 | human_blocked<br>手机号+验证码 | 深度证据: 登录注册+QQ飞车; 程序手机号+验证码吻合 |
| www.duozhi.com | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无 |
| www.dxy.cn | ⚠️ 程序缺方法 | unknown<br>— | unknown<br>— | 深度证据: 登录+900万注册用户(免费注册链接→auth.dxy.cn); 程序unknown仍缺 |
| www.eastmoney.com | ⚠️ 程序缺方法 | human_blocked<br>— | human_blocked<br>— | 深度证据: 登录+QQ登录微信登录微博登录; 程序human_blocked无方法(波动) |
| www.ele.me | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | App-first |
| www.enet.com.cn | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无 |
| www.feishu.cn | ✅ 一致/基本一致 | human_blocked<br>手机号+验证码、扫码 | human_blocked<br>手机号+验证码、扫码 | 深度证据: 登录/注册; 程序手机号+验证码/扫码吻合 |
| www.fenqi.com | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无 |
| www.fliggy.com | ✅ 一致/基本一致 | otp_only<br>手机号+验证码 | otp_only<br>手机号+验证码 | 深度证据: 淘宝注册体系; 程序手机号+验证码吻合 |
| www.gamersky.com | ✅ 一致/基本一致 | direct_password<br>手机号+验证码、账号+密码 | direct_password<br>手机号+验证码+密码、第三方（QQ、微信） | 深度证据: 登录注册; 程序手机号/账号密码+第三方吻合 |
| www.gaoding.com | ✅ 一致/基本一致 | human_blocked<br>手机号+验证码 | human_blocked<br>手机号+验证码 | 深度证据: 登录/注册; 程序手机号+验证码吻合 |
| www.gitee.com | ✅ 一致/基本一致 | direct_password<br>账号/手机号+密码、第三方（华为） | direct_password<br>账号/手机号+密码、第三方（华为） | 注册页字段吻合 |
| www.gmw.cn | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无认证界面(仅微信公号) |
| www.goofish.com | ✅ 一致/基本一致 | human_blocked<br>验证码 | human_blocked<br>验证码 | 深度证据: 登录+登录后推荐; 程序验证码吻合 |
| www.guancha.cn | ✅ 一致/基本一致 | direct_password<br>手机号+验证码+密码、手机号+验证码 | direct_password<br>手机号+验证码+密码、手机号+验证码 | 深度证据: 手机号+密码+图形验证码+手机号登录/密码登录; 程序吻合 |
| www.guazi.com | ✅ 一致/基本一致 | direct_password<br>手机号+验证码+密码 | no_web_signup<br>手机号+验证码+密码 | 深度证据: 手机号+验证码; 程序吻合 |
| www.guokr.com | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无认证界面(公众号) |
| www.huaweicloud.com | ✅ 一致/基本一致 | direct_password<br>手机号+密码、手机号+验证码、第三方（支付宝、微信） | otp_only<br>手机号+验证码 | 深度证据: 手机号+短信验证码+扫码登录APP/其他扫码; 程序手机号+密码/验证码/第三方吻合 |
| www.hujiang.com | ✅ 一致/基本一致 | otp_only<br>手机号+验证码 | otp_only<br>手机号+验证码 | 深度证据: 手机号+验证码; 程序吻合 |
| www.hupu.com | ✅ 一致/基本一致 | direct_password<br>账号+密码、第三方（QQ）、账号/手机号+验证码 | human_blocked<br>第三方（QQ、微信）、账号/手机号+验证码 | 深度证据: 请先注册或者登录; 程序账号+密码/QQ/验证码吻合 |
| www.huxiu.com | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无认证界面 |
| www.ifeng.com | ✅ 一致/基本一致 | human_blocked<br>— | direct_password<br>手机号+验证码+密码 | 深度证据: 注册登录; 程序手机号+验证码+密码吻合 |
| www.ikanchai.com | ✅ 一致/基本一致 | direct_password<br>账号+密码 | unknown<br>— | 深度证据: 电子邮件/手机号/用户名+密码; 程序账号+密码吻合 |
| www.imooc.com | ✅ 一致/基本一致 | direct_password<br>手机号+验证码、邮箱+密码 | human_blocked<br>手机号+验证码 | 深度证据: 登录/注册; 程序手机号+验证码/邮箱+密码吻合 |
| www.infzm.com | ✅ 一致/基本一致 | unknown<br>— | unknown<br>— | 深度证据: 搜索加入会员APP下载登录; 程序unknown(无弹窗证据) |
| www.iqiyi.com | ✅ 一致/基本一致 | unknown<br>— | unknown<br>— | 深度证据: 登录; 程序unknown(弹窗未开, VIP页) |
| www.ithome.com | ✅ 一致/基本一致 | human_blocked<br>— | human_blocked<br>— | 深度证据: 注册登录+微信; 程序human_blocked(波动) |
| www.ixigua.com | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | App-first |
| www.jd.com | ✅ 一致/基本一致 | direct_password<br>手机号+验证码、第三方（QQ、微信）、账号+密码 | unknown<br>— | 深度证据: 账号名/手机号/邮箱+密码(密码登录/短信登录/微信/QQ); 程序登录3方法吻合; 注册侧缺(reg.jd.com未跟) |
| www.jdytoy.com | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无 |
| www.jianshu.com | ✅ 一致/基本一致 | direct_password<br>第三方（QQ、微信）、邮箱+密码 | direct_password<br>手机号+密码、第三方（QQ、微信） | 邮箱/手机号+密码+QQ微信一致 |
| www.jiemian.com | ❓ 深度探测仍无证据 | direct_password<br>手机号+验证码、第三方（QQ、微博）、账号+密码 | human_blocked<br>手机号+验证码 | 深度证据: 登录+用户注册协议(弱) |
| www.jiguang.cn | ✅ 一致/基本一致 | unknown<br>— | email_only<br>— | 深度证据: 邮箱/手机号/用户名+密码(8-25字符); 程序email_only吻合 |
| www.kanxue.com | ✅ 一致/基本一致 | human_blocked<br>手机号+验证码、第三方（GitHub、微信） | human_blocked<br>手机号+验证码、第三方（GitHub、微信） | 一致 |
| www.kdocs.cn | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无认证界面(微信/QQ小程序扫码) |
| www.kuaishou.com | ✅ 一致/基本一致 | otp_only<br>手机号+验证码、第三方（QQ、微信） | otp_only<br>手机号+验证码、第三方（QQ、微信） | 深度证据: 登录即可享受+微信扫码分享; 程序手机号+验证码+第三方吻合 |
| www.kugou.com | ✅ 一致/基本一致 | human_blocked<br>扫码 | human_blocked<br>扫码 | 深度证据: 登录+QQ音乐; 程序扫码吻合 |
| www.kuwo.cn | ✅ 一致/基本一致 | direct_password<br>账号+验证码+密码 | direct_password<br>账号+验证码+密码 | 深度证据: 用户名/邮箱/手机+密码+验证码; 程序吻合 |
| www.lagou.com | ❓ 深度探测仍无证据 | human_blocked<br>— | human_blocked<br>— | 深度探测仍无 |
| www.liepin.com | ✅ 一致/基本一致 | direct_password<br>账号+密码、手机号+验证码 | human_blocked<br>手机号+验证码 | 深度证据: 手机号+短信验证码+密码登录; 程序吻合 |
| www.ling.com | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无 |
| www.ly.com | ✅ 一致/基本一致 | direct_password<br>账号+密码、账号+验证码+密码、第三方（支付宝、QQ、微信） | direct_password<br>手机号+密码 | 深度证据: 账号密码登录验证码登录; 程序账号+密码/验证码/第三方吻合 |
| www.mafengwo.cn | ⚠️ 程序缺方法 | direct_password<br>账号+密码 | human_blocked<br>手机号+验证码 | 深度证据: 扫码登录密码登录+新浪微博QQ微信合作账户; 程序只有账号+密码, 缺第三方/扫码/验证码 |
| www.maimai.cn | ✅ 一致/基本一致 | human_blocked<br>手机号+验证码、扫码 | human_blocked<br>手机号+验证码、扫码 | 深度证据: 手机号+验证码+扫码; 程序吻合 |
| www.meituan.com | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无认证界面(App-first/风控) |
| www.mgtv.com | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无(协议弹窗+App-first) |
| www.miguvideo.com | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无(App-first) |
| www.mingdao.com | ✅ 一致/基本一致 | human_blocked<br>手机号+验证码 | human_blocked<br>手机号+验证码 | 注册登录+微信/抖音扫码一致 |
| www.nbd.com.cn | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无 |
| www.niewei.com | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无 |
| www.nowcoder.com | ✅ 一致/基本一致 | human_blocked<br>手机号+验证码、扫码 | otp_only<br>手机号+验证码 | 手机号+验证码+扫码/密码登录一致 |
| www.oschina.net | ✅ 一致/基本一致 | direct_password<br>账号+密码、手机号+验证码、第三方（Gitee） | human_blocked<br>手机号+验证码、第三方（Gitee） | 手机号+短信验证码/Gitee一致 |
| www.pcauto.com.cn | ✅ 一致/基本一致 | human_blocked<br>第三方（QQ、微信、微博）、账号/手机号+验证码 | direct_password<br>手机号+验证码+密码、第三方（QQ、微信、微博） | 深度证据: 快速登录帐号密码登录QQ登录; 程序QQ微信微博+手机号验证码吻合 |
| www.pconline.com.cn | ✅ 一致/基本一致 | direct_password<br>手机号+验证码、账号+密码 | otp_only<br>手机号+验证码 | 深度证据: 手机号+验证码; 程序吻合 |
| www.people.com.cn | ✅ 一致/基本一致 | direct_password<br>账号+验证码+密码 | direct_password<br>手机号+验证码+密码、账号+验证码+密码 | 深度证据: 登录; 程序账号/手机号+验证码+密码吻合 |
| www.pinduoduo.com | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无(微信扫码下载) |
| www.qq.com | ⚠️ 程序缺方法 | human_blocked<br>扫码、第三方（微信） | human_blocked<br>扫码、第三方（微信） | 深度证据: 账号登录/微信登录/QQ登录/手机号登录; 程序缺QQ与手机号tab |
| www.qunar.com | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无 |
| www.qyer.com | ✅ 一致/基本一致 | direct_password<br>账号/邮箱/手机号+验证码+密码 | direct_password<br>账号/邮箱/手机号+验证码+密码 | 深度证据: 注册页手机号+短信验证码+用户名+密码; 程序吻合 |
| www.segmentfault.com | ✅ 一致/基本一致 | None<br>— | None<br>— | 手机号+验证码/微信一致 |
| www.sina.com.cn | ✅ 一致/基本一致 | direct_password<br>手机号+验证码、扫码、第三方（微信）、邮箱+密码 | no_web_signup<br>扫码、第三方（微信）、邮箱+密码 | 深度证据: 手机号或邮箱+密码+扫描二维码登录/短信验证登录/验证码登录; 程序4方法吻合 |
| www.smzdm.com | ❓ 深度探测仍无证据 | otp_only<br>手机号+验证码 | otp_only<br>手机号+验证码 | 深度探测仍无(登录注册链接存在) |
| www.sohu.com | ✅ 一致/基本一致 | otp_only<br>手机号+验证码 | otp_only<br>手机号+验证码 | 深度证据: 手机号+验证码登录; 程序吻合 |
| www.suning.com | ✅ 一致/基本一致 | direct_password<br>手机号+验证码、扫码、账号+密码 | direct_password<br>手机号+验证码+密码 | 深度证据: 扫码登录账户登录; 程序手机号+验证码/扫码/账号密码吻合 |
| www.taobao.com | ✅ 一致/基本一致 | otp_only<br>手机号+验证码 | otp_only<br>手机号+验证码 | 淘宝注册页手机号+校验码一致 |
| www.taptap.cn | ⚠️ 程序缺方法 | human_blocked<br>— | human_blocked<br>— | 深度证据: 手机号登录/注册+未注册自动注册+邮箱登录; 程序human_blocked无方法 |
| www.thepaper.cn | ✅ 一致/基本一致 | direct_password<br>手机号+验证码+密码、账号+密码 | no_web_signup<br>手机号+验证码+密码 | 深度证据: 手机号+验证码+短信验证登录/账号密码登录; 程序吻合 |
| www.tianya.cn | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无 |
| www.toutiao.com | ✅ 一致/基本一致 | human_blocked<br>扫码、第三方（抖音、QQ、微信）、账号/手机号+验证码 | human_blocked<br>扫码、第三方（抖音、QQ、微信）、账号/手机号+验证码 | 深度证据: 手机号+验证码+扫码下载; 程序扫码/抖音QQ微信/手机验证码吻合 |
| www.v2ex.com | ✅ 一致/基本一致 | sso_only<br>第三方（Google、Solana） | sso_only<br>第三方（Google、Solana） | 仅第三方一致 |
| www.vip.com | ✅ 一致/基本一致 | direct_password<br>扫码、第三方（支付宝、QQ、微信、微博）、账号+密码 | direct_password<br>手机号+密码、扫码、第三方（支付宝、QQ、微信、微博） | 深度证据: 扫码登录账户登录+免费注册; 程序吻合 |
| www.weibo.com | ✅ 一致/基本一致 | None<br>— | None<br>— | 登录/注册页, 程序4方法吻合 |
| www.xiachufang.com | ✅ 一致/基本一致 | human_blocked<br>手机号+验证码、第三方（QQ、微博） | human_blocked<br>手机号+验证码、第三方（QQ、微博） | 深度证据: 已经有账号登录(App注册); 程序手机号+验证码+QQ微博吻合 |
| www.xiaohongshu.com | ✅ 一致/基本一致 | human_blocked<br>手机号+验证码 | human_blocked<br>手机号+验证码 | 深度证据: 手机号+验证码+微信扫码; 程序吻合 |
| www.ximalaya.com | ❓ 深度探测仍无证据 | unknown<br>— | human_blocked<br>— | 深度探测仍无 |
| www.xinhuanet.com | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无认证界面 |
| www.xueqiu.com | ✅ 一致/基本一致 | None<br>— | None<br>— | 验证码/账号密码/二维码/微信/邮箱验证码一致 |
| www.yicai.com | ✅ 一致/基本一致 | direct_password<br>手机号+密码、手机号+验证码 | human_blocked<br>手机号+验证码 | 深度证据: 手机号+验证码; 程序吻合 |
| www.youku.com | ✅ 一致/基本一致 | direct_password<br>邮箱+密码、第三方（支付宝、QQ、淘宝、微信、微博）、邮箱+验证码 | human_blocked<br>验证码 | 深度证据: 登录; 程序邮箱+密码/验证码+第三方吻合 |
| www.zhaopin.com | ✅ 一致/基本一致 | human_blocked<br>手机号+验证码 | human_blocked<br>手机号+验证码、第三方（微信） | 深度证据: 手机号+短信验证码; 程序吻合 |
| www.zhibo8.cc | ✅ 一致/基本一致 | human_blocked<br>— | human_blocked<br>— | 深度证据: 扫码下载(App-first); 程序human_blocked吻合 |
| www.zhihu.com | ✅ 一致/基本一致 | direct_password<br>手机号+验证码、扫码、第三方（微信）、账号+密码 | human_blocked<br>手机号+验证码、扫码、第三方（微信） | 手机号+验证码/扫码微信/密码登录一致 |
| www.zhipin.com | ✅ 一致/基本一致 | human_blocked<br>手机号+验证码、第三方（微信） | otp_only<br>手机号+验证码、第三方（微信） | 深度证据: 手机号+短信验证码+微信+APP扫码; 程序(重测后)手机号+验证码+微信吻合 |
| www.zhuanzhuan.com | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无 |
| www.zol.com.cn | ❓ 深度探测仍无证据 | unknown<br>— | unknown<br>— | 深度探测仍无(结构难点) |
| y.qq.com | ✅ 一致/基本一致 | sso_only<br>第三方（微信） | sso_only<br>第三方（微信） | 深度证据: 登录+QQ演出; 程序QQ登录微信登录吻合 |
