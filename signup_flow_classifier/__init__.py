"""注册流程分类器 — 嫁接自 MyAutomaticPolicy 的 signup_flow 模块。

提供注册/登录页面流程类型自动分类（A-I 九类）：
  A  direct_password              当前页面直接出现邮箱/用户名和口令框
  B  identifier_then_password     先填邮箱或手机号，点击下一步后才出现口令框
  C  verification_then_password   先通过短信或邮箱验证码，之后才能设置口令
  D  otp_only                     验证码注册，无长期静态口令
  E  multiple_methods             同时提供多种注册方式
  F  sso_only                     只有第三方登录
  G  human_blocked                被验证码/扫码挡住
  H  no_web_signup                没有可用网页注册入口
  I  unknown                      页面异常或证据不足

用法：
    from signup_flow_classifier.classifier_engine import SignupFlowClassifierEngine
    engine = SignupFlowClassifierEngine(driver)
    result = engine.classify(signup_url)
"""
