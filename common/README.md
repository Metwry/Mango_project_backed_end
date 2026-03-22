# Common Module / 公共基础模块

## 中文

- 定位：封装跨 app 复用的公共能力。
- 当前内容：统一异常处理、日志工具，以及集中在 `common/utils/` 下的数据库约束、时间桶、汇率、代码、日期和金额工具。
- 设计思路：把横切逻辑从业务 app 中抽离，减少重复实现并统一错误口径。

## English

- Role: holds reusable cross-cutting infrastructure common to multiple apps.
- Current content: exception handling, logging helpers, and a single `common/utils/` entry for database constraints, time buckets, FX helpers, code/date, and decimal utilities.
- Design: pull cross-cutting concerns out of domain apps to reduce duplication and keep behavior consistent.
