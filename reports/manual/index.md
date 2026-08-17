# 人工核验总览（由 misc/manual_review.json 生成，2026-08-17）

> 本目录是人工核验的**衍生可读报告**；权威数据仍在 `misc/manual_review.json`。

已核验 124 站。

| 站点 | 登录（人工） | 注册（人工） | 登录口令判定 | 注册口令判定 | 总判定 |
|---|---|---|---|---|---|
| 36kr.com | 登录后直接手机号验证码，无密码框 | 手机号+短信验证码注册，无密码 | none | none | none |
| cloud.tencent.com | 手机号/邮箱+密码登录 | 手机号+密码注册 | inline | inline | inline |
| deeix.gaoxiaobei.top | 账号+密码 | 无注册界面 | — | — | — |
| juejin.cn | 手机号+验证码，可切密码登录 | 手机号+验证码注册，无密码 | none | none | none |
| leetcode.cn | 手机号+验证码，可切密码 | 手机号+验证码注册，无密码 | none | none | none |
| music.163.com | 扫码登录 | 扫码/手机验证注册 | none | none | none |
| pan.baidu.com | 扫码/手机验证码登录 | 百度账号注册，手机+密码 | inline | inline | inline |
| segmentfault.com | 手机号+验证码 | 手机号+验证码注册，无密码 | none | none | none |
| shimo.im | 账号邮箱+密码 | 无独立注册表单，仅登录界面 | full | none | full |
| tieba.baidu.com | 扫码登录 | 百度安全验证+扫码，注册按钮藏在登录里 | inline | inline | inline |
| v.qq.com | 扫码+手机验证码 | 扫码/手机验证注册 | none | none | none |
| web.okjike.com | 扫码登录注册 | 扫码登录注册 | none | none | none |
| weibo.com | 手机号+验证码，可密码 | 手机号+验证码注册，无密码 | none | none | none |
| work.weixin.qq.com | 扫码登录 | 仅企业微信，第三方登录 | none | none | none |
| www.10jqka.com.cn | 手机号+验证码，可密码 | 手机号+验证码+密码注册（先验证后口令） | inline | inline | inline |
| www.12306.cn | 账号+密码 | 账号+密码注册（首页点注册或登录页点注册12306账号） | inline | inline | inline |
| www.163.com | 邮箱/手机+密码 | 手机号+密码注册 | inline | inline | inline |
| www.2345.com | 手机+验证码；用户名（账号）+密码；第三方 | 手机+验证码 | — | — | — |
| www.3dmgame.com | 手机+验证码；手机+密码；app扫码 | 手机+验证码+密码 | — | — | — |
| www.51cto.com | 手机号+验证码，可密码 | 手机号+验证码注册，无密码（危险模式：仅登录） | full | none | full |
| www.51job.com | 扫码；手机号+验证码+协议；手机号+口令+协议 | 手机号+验证码；手机号+口令 | none | none | none |
| www.52pojie.cn | 邮箱+密码 | 邮箱+密码注册（需勾选用户须知） | inline | inline | inline |
| www.58.com | 手机号+验证码 | 手机号+验证码+密码注册 | inline | inline | inline |
| www.acfun.cn | 账号+密码 | 注册表单藏在登录界面，手机+验证码+密码 | inline | inline | inline |
| www.aliyun.com | 账号+密码 | 手机号+验证码注册，还有其他第三方验证方式 | full | full | full |
| www.amap.com | 扫码+手机号验证码 | 手机号+验证码注册 | full | full | full |
| www.anjuke.com | 手机号+验证码 | 手机号+验证码注册（有验证块） | full | full | full |
| www.autohome.com.cn | 第三方；扫码；手机号+验证码+人机验证+协议；手机号+口令+人机验证+协议 | 无注册界面 | full | none | full |
| www.baidu.com | 账号+密码/短信 | 百度账号注册，手机+密码（危险模式：仅登录界面） | full | none | full |
| www.bilibili.com | 账号+密码/扫码 | 手机号+验证码注册，无密码（危险模式：仅登录） | full | none | full |
| www.caixin.com | 手机号+密码 | 手机号+密码注册（危险模式） | full | none | full |
| www.cctv.com | 账号+密码 | 注册表单藏在登录界面 | inline | inline | inline |
| www.china.com | 账号+密码 | 注册表单藏在登录界面 | inline | inline | inline |
| www.chinanews.com | 无登录注册表单 | 无登录注册表单 | none | none | none |
| www.cnblogs.com | 邮箱+密码 | 手机号+密码注册 | inline | inline | inline |
| www.coolapk.com | 无登录注册表单，扫码下载误判 | 无登录注册表单 | none | none | none |
| www.csdn.net | 扫码登录 | 扫码注册 | full | full | full |
| www.ctrip.com | 手机号+验证码 | 手机号+验证码注册（B类，解决手机号后有测政策机会） | full | full | full |
| www.dangdang.com | 手机号+验证码 | 手机号+密码注册 | full | full | full |
| www.dewu.com | 无登录注册表单，扫码下载误判 | 无登录注册表单 | none | none | none |
| www.dianping.com | 手机号+验证码（有验证块） | 手机号+验证码注册 | none | none | none |
| www.dingtalk.com | 手机号 | 手机号+验证码（B类未正确识别） | full | none | full |
| www.dongchedi.com | 手机号+验证码 | 手机号+验证码注册（危险模式：仅登录） | full | none | full |
| www.dongqiudi.com | 需下载 App | 需下载 App | none | none | none |
| www.douban.com | 手机号+验证码 | 手机号+验证码 | none | none | none |
| www.douyin.com | 账号/手机号+密码、账号/手机号+验证码 | 账号/手机号+验证码 | none | none | none |
| www.douyu.com | 手机号+验证码 | 手机号+验证码 | none | none | none |
| www.dxy.cn | 第三方登录 | 第三方登录 | none | none | none |
| www.eastmoney.com | 手机号+验证码 | 手机号+验证码 | none | none | none |
| www.ele.me | 需下载 App | 需下载 App | none | none | none |
| www.feishu.cn | 手机号+验证码、扫码 | 手机号+验证码、扫码 | none | none | none |
| www.fliggy.com | 手机号+验证码 | 手机号+验证码 | none | none | none |
| www.gamersky.com | 手机号+验证码、账号+密码 | 手机号+验证码+密码、第三方（QQ、微信） | none | none | none |
| www.gitee.com | 账号/手机号+密码、第三方（华为） | 账号/手机号+密码、第三方（华为） | inline | inline | inline |
| www.gmw.cn | 无注册界面 | 无注册界面 | none | none | none |
| www.goofish.com | 验证码 | 验证码 | none | none | none |
| www.guancha.cn | 手机号+验证码+密码、手机号+验证码 | 手机号+验证码+密码、手机号+验证码 | none | none | none |
| www.guokr.com | 无注册界面 | 无注册界面 | none | none | none |
| www.huaweicloud.com | 手机号+密码、手机号+验证码、第三方（支付宝、微信） | 手机号+验证码 | full | full | full |
| www.hupu.com | 账号+密码、第三方（QQ）、账号/手机号+验证码 | 第三方（QQ、微信）、账号/手机号+验证码 | none | none | none |
| www.huxiu.com | 无注册界面 | 无注册界面 | none | none | none |
| www.huya.com | 手机号+密码、手机号+验证码 | 手机号+密码、手机号+验证码+密码 | none | none | none |
| www.ifeng.com |  | 手机号+验证码+密码 | inline | inline | inline |
| www.imooc.com | 手机号+验证码、邮箱+密码 | 手机号+验证码 | none | none | none |
| www.infzm.com | 手机号+验证码 | 手机号+验证码 | none | none | none |
| www.iqiyi.com | 手机号+验证码 | 手机号+验证码 | none | none | none |
| www.ithome.com | 手机号+验证码 | 手机号+验证码 | none | none | none |
| www.ixigua.com | 需下载 App | 需下载 App | none | none | none |
| www.jd.com | 手机号+验证码、第三方（QQ、微信）、账号+密码 | 手机号+验证码 | none | none | none |
| www.jianshu.com | 第三方（QQ、微信）、邮箱+密码 | 手机号+密码、第三方（QQ、微信） | full | full | full |
| www.jiemian.com | 手机号+验证码、第三方（QQ、微博）、账号+密码 | 手机号+验证码 | none | none | none |
| www.kanxue.com | 手机号+验证码、第三方（GitHub、微信） | 手机号+验证码、第三方（GitHub、微信） | none | none | none |
| www.kdocs.cn | 需下载 App | 需下载 App | none | none | none |
| www.ke.com | 手机号+验证码+密码 | 手机号+验证码+密码 | full | full | full |
| www.kuaishou.com | 手机号+验证码、第三方（QQ、微信） | 手机号+验证码、第三方（QQ、微信） | none | none | none |
| www.kugou.com | 扫码 | 扫码 | none | none | none |
| www.kuwo.cn | 账号+验证码+密码 | 账号+验证码+密码 | full | full | full |
| www.lagou.com | 手机号+验证码 | 手机号+验证码 | none | none | none |
| www.lianjia.com | 手机号+验证码+密码 | 手机号+验证码+密码 | full | full | full |
| www.liepin.com | 账号+密码、手机号+验证码 | 手机号+验证码 | none | none | none |
| www.ly.com | 账号+密码、账号+验证码+密码、第三方（支付宝、QQ、微信） | 手机号+密码 | inline | inline | inline |
| www.mafengwo.cn | 账号+密码 | 手机号+验证码 | none | none | none |
| www.maimai.cn | 手机号+验证码、扫码 | 手机号+验证码、扫码 | none | none | none |
| www.meituan.com | 无登录注册界面 | 无登录注册界面 | none | none | none |
| www.mgtv.com | 需点同意用户协议弹窗，右上头像登录/注册 | 短信登录后自动注册 | full | full | full |
| www.miguvideo.com | 右上头像登录，微博/短信/密码 | 密码登录内点注册，需短信验证 | full | full | full |
| www.nbd.com.cn | 无登录注册界面 | 无登录注册界面 | none | none | none |
| www.nowcoder.com | 手机号+验证码 | 邮箱-人机验证-口令（备选） | full | full | full |
| www.oschina.net | 手机号+验证码，可密码 | 手机号+验证码注册，有第三方(Gitee) | full | full | full |
| www.pcauto.com.cn | 手机号+验证码 | 手机+密码注册，除滑块还需手机验证码 | inline | inline | inline |
| www.pconline.com.cn | 手机号+验证码，有第三方 | 手机号+验证码注册，有第三方 | inline | inline | inline |
| www.people.com.cn | 账号+密码 | 手机号+短信验证码+设置密码注册 | inline | inline | inline |
| www.pinduoduo.com | 无直接登录界面，仅商家入驻 | 商家入驻注册需手机+密码+验证码 | inline | inline | inline |
| www.qq.com | 扫码+手机验证码+第三方 | 扫码注册 | none | none | none |
| www.qunar.com | 无登录注册选项 | 无登录注册选项 | none | none | none |
| www.qyer.com | 手机+密码 | 手机+验证码+用户名+密码注册 | inline | inline | inline |
| www.sina.com.cn | 邮箱/手机+密码 | 第三方/app扫码/手机+验证码注册 | full | full | full |
| www.smzdm.com | 登录有密码框 | 注册仅手机+验证码，有第三方 | full | full | full |
| www.sohu.com | 手机号+验证码，有第三方 | 手机号+验证码注册，有第三方 | none | none | none |
| www.suning.com | 账号+密码 | 注册需跳转+同意注册协议 | inline | inline | inline |
| www.taobao.com | 手机号+验证码 | 手机号+验证码注册，另有企业注册 | none | none | none |
| www.taptap.cn | 右上头像登录，需人机验证+有效手机号 | 手机号+验证码注册 | none | none | none |
| www.thepaper.cn | 登录有密码框 | 仅手机+验证码注册，无二维码界面 | full | full | full |
| www.tianya.cn | 无法登录 | 无法登录 | none | none | none |
| www.toutiao.com | 手机号+验证码+第三方 | 手机号+验证码注册 | none | none | none |
| www.tuniu.com | 手机号+验证码 | 手机验证后出现密码框，还有动态验证码 | none | none | none |
| www.v2ex.com | google/solana 第三方登录 | google/solana 注册 | none | none | none |
| www.vip.com | 手机号+密码 | 先进入登录界面再点注册进入注册界面，密码框直接表明密码政策 | inline | inline | inline |
| www.xiachufang.com | 仅扫码登录 | 仅扫码登录 | none | none | none |
| www.xiaohongshu.com | 手机号+验证码+第三方扫码 | 手机号+验证码注册，+第三方(小红书/微信) | none | none | none |
| www.xinhuanet.com | 无登录注册界面 | 无登录注册界面 | none | none | none |
| www.yicai.com | 手机号+密码 | 手机号+密码注册 | full | full | full |
| www.yiche.com | 手机号+密码 | 手机号+密码注册 | full | full | full |
| www.youku.com | 手机号+密码/验证码 | 仅登录界面，第三方(淘宝/支付宝/微信)或手机+验证码注册 | full | full | full |
| www.zcool.com.cn | 扫码登录 | 注册+第三方，手机注册需滑块 | none | none | none |
| www.zhaopin.com | 手机号+验证码+微信sso(藏左上角) | 手机号+验证码注册 | none | none | none |
| www.zhibo8.cc | 手机号+验证码 | 手机号+验证码注册 | none | none | none |
| www.zhihu.com | 账号邮箱+密码，可扫码/第三方 | 扫码/第三方注册（扫码后无需口令） | full | full | full |
| www.zhipin.com | 手机+验证码或微信sso，可扫码 | 手机+验证码或微信sso注册 | none | none | none |
| www.zhuanzhuan.com | 无登录注册界面 | 无登录注册界面 | none | none | none |
| www.zol.com.cn | 右上角登录，账号登录里藏注册 | 手机+密码+人机+短信验证码注册 | inline | inline | inline |
| xueqiu.com | 微信sso+账密登录 | 无注册界面，手机+验证码自动注册 | full | full | full |
| y.qq.com | 第三方扫码/邮箱手机+密码 | 注册藏在qq登录里，手机+短信+昵称+密码+协议 | inline | inline | inline |
| you.163.com | 扫码/手机短信/手机密码/邮箱密码/第三方sso | 注册在邮箱登录里，邮箱+密码+协议 | inline | inline | inline |
