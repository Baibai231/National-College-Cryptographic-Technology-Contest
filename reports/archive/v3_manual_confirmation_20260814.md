# v3 三次不一致项定点确认

- `www.eastmoney.com / signup`：第四次定点确认再次得到 `human_blocked`，页面出现 captcha/滑块门槛；最终采用差异复测记录。
- `www.iqiyi.com / login`：第四次定点确认仍为 `unknown`，落到会员页且未取得认证字段；三次差异仅是停止原因/是否出现 `auto_signup` 提示，不改变最终流程类型。
- `music.163.com / login, signup`：第一轮取得完整 `human_blocked` 证据；第二轮与差异复测均发生渲染器超时。最终采用唯一成功测量，不把失败次数作为流程投票。
