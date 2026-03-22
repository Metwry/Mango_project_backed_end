# Common Module / 公共基础模块

## 中文

- 定位：封装跨 app 复用的公共能力。
- 当前内容：统一异常处理，`common/normalize.py` 下的代码/时间/金额规范化工具，以及 `common/utils.py` 下的日志、数据库约束、时间桶等通用工具。
- 设计思路：把横切逻辑从业务 app 中抽离，减少重复实现并统一错误口径。

## English

- Role: holds reusable cross-cutting infrastructure common to multiple apps.
- Current content: exception handling, normalization helpers in `common/normalize.py`, plus `common/utils.py` for logging, database constraints, and time-bucket utilities.
- Design: pull cross-cutting concerns out of domain apps to reduce duplication and keep behavior consistent.
