"""
full_form_tester — 完整表单密码政策测试模块

适用于需要填写完整注册表单并提交后才能在服务端响应中
获取密码合规反馈的网站（区别于内联实时验证型网站）。

包含:
  - rate_controller:    人类行为节奏模拟与频率控制
  - data_generator:     智能虚拟数据生成（含中文姓名库）
  - password_error_parser: 服务端密码错误反馈解析
  - field_classifier:   表单字段全量检测与类型分类
  - form_submitter:     表单填充 / 提交 / 反馈捕获
  - full_form_tester:   主编排器
"""

from .rate_controller import RateController
from .data_generator import DataGenerator
from .password_error_parser import PasswordErrorParser
from .field_classifier import FieldClassifier
from .form_submitter import FormSubmitter
from .full_form_tester import FullFormPolicyTester

__all__ = [
    "RateController",
    "DataGenerator",
    "PasswordErrorParser",
    "FieldClassifier",
    "FormSubmitter",
    "FullFormPolicyTester",
]
