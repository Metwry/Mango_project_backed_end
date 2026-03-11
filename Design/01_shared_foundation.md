# Shared Foundation Design

## 1. 模块定位

`shared` 不是业务 app，而是整个项目的基础设施层。它解决的不是“业务是什么”，而是“不同业务域如何用一套统一口径处理异常、时间、Decimal、代码归一化和数据库约束”。

## 2. 设计目标

- 减少各业务域重复实现基础逻辑
- 保持异常返回格式一致
- 保持时间、Decimal、代码规范处理一致
- 为 Django 版本差异提供统一兼容层

## 3. 子模块组成

### 3.1 异常与错误响应

- `shared.exceptions`
  - `BusinessConflictError`
  - `LoginFailedError`
- `shared.exception_handler`
  - 把 DRF 默认错误结构压平成前端可直接消费的 `message`

这是一个明确的前后端契约设计：前端只依赖 `message`，后端统一裁剪 `detail` 和嵌套字段。

### 3.2 数据库约束兼容层

- `shared.db.check_constraint`

作用：

- 兼容 Django 5.1 前后的 `CheckConstraint` 参数差异
- 让业务模型直接表达约束，而不是散落在版本分支判断中

### 3.3 工具函数

- `shared.utils.code_utils`
  - 代码标准化、市场后缀处理、短代码解析
- `shared.utils.datetime_utils`
  - 时间转 UTC
- `shared.utils.decimal_utils`
  - Decimal 转换、裁剪和量化
- `shared.utils.cache_utils`
  - 缓存 payload 安全读取

### 3.4 时间桶能力

- `shared.time.buckets`
  - `floor_bucket`
  - `ceil_bucket`
  - `build_bucket_axis`

这是 `snapshot` 的关键基础设施，负责把查询窗口和落库时间统一到 `M15/H4/D1/MON1` 的桶边界。

### 3.5 常量与汇率规范化

- `shared.constants.market`
  - 市场到默认货币的映射
- `shared.fx.rates`
  - USD 汇率表标准化

### 3.6 日志工具

- `shared.logging_utils`

提供结构化字段日志拼接，主要被 `market` 和 Celery 任务使用。

### 3.7 通用 API 基类

- `shared.api.SerializerPostAPIView`

当前项目大多数接口仍直接使用 `APIView`，这个基类存在但使用不广，说明项目更偏向“显式控制 view 逻辑”，而不是完全抽象通用接口模板。

## 4. 设计思路

`shared` 的设计思路可以概括为三点：

1. 只放跨域稳定能力，不放业务语义
2. 尽量保持纯函数和轻依赖
3. 统一边界条件处理，避免各 app 自己发明一套口径

## 5. 依赖关系

### 5.1 输出依赖

`shared` 被以下模块直接依赖：

- `login`
- `accounts`
- `market`
- `investment`
- `snapshot`
- `mango_project.settings`

### 5.2 输入依赖

`shared` 基本不依赖业务 app，这保证了它可以保持为底层稳定层。

## 6. 关键设计价值

- 保证所有接口的错误消息格式一致
- 保证金额和时间的精度/标准化行为一致
- 减少模型层约束声明的重复与版本兼容问题
- 为快照、行情和交易三大域提供共同基础语言

## 7. 当前边界判断

当前 `shared` 的边界总体合理，没有明显越界到业务域。后续如果重构项目，`shared` 应继续保持“低耦合、纯基础设施”的定位，不建议把业务服务挪进来。
