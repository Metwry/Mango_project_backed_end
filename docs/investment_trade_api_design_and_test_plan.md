# 投资交易接口改造与测试方案（基于当前代码扫描）

## 1. 扫描范围与当前现状

### 1.1 当前交易相关模型

- `investment.models.InvestmentRecord`
  - 已支持 `side = BUY/SELL`。
  - `BUY` 必须 `realized_pnl = NULL`，`SELL` 必须 `realized_pnl != NULL`（模型校验 + DB 约束）。
- `investment.models.Position`
  - 持仓唯一键：`(user, instrument)`。
  - 字段：`quantity / avg_cost / cost_total`，都为 6 位小数。
- `accounts.models.Transaction`
  - 保存时会自动更新账户余额并写入 `balance_after`。
  - 不允许删除，支持 `reverse`（冲正）动作。

### 1.2 当前接口状态

- 已有买入接口：`POST /api/investment/buy/`
  - 视图：`investment.views.InvestmentBuyView`
  - 业务：`investment.serializers.InvestmentBuySerializer.create`
- 尚无卖出接口：`/api/investment/sell/`（未实现）

### 1.3 当前买入业务链路（已实现）

在一个事务内完成：

1. 校验标的存在且可交易
2. 锁定资金账户（`select_for_update`）并校验归属/启用/币种
3. 锁定或创建持仓（处理并发创建竞争）
4. 计算买入成本并校验余额
5. 写 `accounts_transaction` 资金流水（负数扣款）
6. 更新 `Position`（数量、总成本、均价）
7. 写 `InvestmentRecord`（`side=BUY`）

现有并发测试已覆盖“同账户同标的并发买入串行化”。

## 2. 接口设计建议（修改或新增）

## 2.1 推荐方案：统一核心服务 + 语义路由

保持你当前的路由风格，建议这样落地：

- 保留：`POST /api/investment/buy/`
- 新增：`POST /api/investment/sell/`
- 可选新增（后续）：`POST /api/investment/trades/` + `side=BUY|SELL`

关键点：

- `buy/sell/trades` 三个入口都调用同一个服务层（例如 `TradeService.execute_trade(...)`）。
- 公共校验、账户同步、持仓更新、投资记录写入都只保留一套核心实现。
- 避免买入和卖出出现“双份逻辑漂移”。

## 2.2 卖出接口最小可行定义（建议先落地）

### 请求

`POST /api/investment/sell/`

```json
{
  "instrument_id": 1,
  "quantity": "1.500000",
  "price": "12.340000",
  "cash_account_id": 2,
  "trade_at": "2026-02-28T08:30:00Z"
}
```

### 响应（示例）

```json
{
  "investment_record_id": 10,
  "position": {
    "quantity": "0.500000",
    "avg_cost": "10.500000",
    "cost_total": "5.250000"
  },
  "transaction_id": 88,
  "balance_after": "118.51",
  "realized_pnl": "2.76"
}
```

### 核心业务规则

1. 校验持仓足够：`position.quantity >= quantity`
2. 卖出金额入账：`amount = +(quantity * price)`（按账户精度量化到 2 位）
3. 已实现盈亏：
   - `sell_proceeds = quantity * price`
   - `cost_released = position.avg_cost * quantity`
   - `realized_pnl = sell_proceeds - cost_released`
4. 更新持仓：
   - `new_quantity = old_quantity - quantity`
   - `new_cost_total = old_cost_total - cost_released`
   - 若 `new_quantity == 0`，则强制 `avg_cost = 0`、`cost_total = 0`
5. 写 `InvestmentRecord(side=SELL, realized_pnl=...)`
6. 所有步骤在同一 `transaction.atomic()` 中执行

## 3. 代码改动建议（按你当前项目结构）

## 3.1 investment 层

- `investment/serializers.py`
  - 抽公共基类：`InvestmentTradeBaseSerializer`（公共字段与校验）
  - 新增：`InvestmentSellSerializer`
  - 可选：新增通用 `InvestmentTradeSerializer(side)`
- `investment/views.py`
  - 新增：`InvestmentSellView`
- `investment/urls.py`
  - 新增路由：`path("investment/sell/", InvestmentSellView.as_view(), name="investment-sell")`

## 3.2 事务一致性与锁

- 继续保持：
  - 账户行 `select_for_update`
  - 持仓行 `select_for_update`
- 建议统一锁顺序（先账户后持仓）以降低死锁风险。

## 3.3 与 `accounts.Transaction.reverse` 的关系（高优先级关注）

当前任意交易流水可冲正，但投资买卖会同步影响持仓。
如果只冲正资金流水，不回滚持仓，会造成账实不一致。

对投资交易生成的资金流水，禁止直接走通用 `reverse`；

## 4. 现有潜在风险清单（扫描结论）

1. 小额舍入漏洞风险（高）
- 当前资金入账精度是 2 位；极小金额 `quantity * price` 可能量化后为 `0.00`，导致可“0 成本买入”增加持仓。
- 建议：若量化后金额 `<= 0` 直接拒绝，或限制最小成交额。

2. 交易流水可冲正导致投资侧不一致（高）
- 目前 `accounts` 的 `reverse` 不感知 `investment` 持仓状态。

3. 缺少幂等控制（中）
- 网络重试可能造成重复下单。
- 建议增加 `client_order_id`（user 维度唯一）。

4. `category_name` 长度溢出（中）
- `Transaction.category_name(max_length=24)`；价格/数量较大时字符串可能超长。
- 建议改为模板化短文案 + 关键信息放扩展字段，或提升长度。

5. 账户类型未限制（低~中）
- 目前仅校验归属、状态、币种，未限制必须为券商账户类型（`BROKER`）。

## 5. 测试用例方案（重点覆盖复杂/高风险逻辑）

以下用例建议放在 `investment/tests.py`，优先使用 `APITestCase + TransactionTestCase`。

## 5.1 买入接口补充用例

1. `test_buy_rejects_tiny_cost_rounded_to_zero`
- 输入极小 `quantity/price`，使金额量化后为 `0.00`
- 期望：返回 400/409，且不创建持仓、不写流水

2. `test_buy_rejects_inactive_account`
- 账户状态 `disabled/archived`
- 期望：409

3. `test_buy_category_name_length_safe`
- 构造大数字触发文案长度边界
- 期望：不报 DB 异常（或按设计返回校验错误）

## 5.2 卖出接口核心用例（新增）

1. `test_sell_success_updates_position_account_and_record`
- 先买入再卖出部分仓位
- 断言：
  - 账户余额增加正确
  - 持仓数量与成本正确
  - `InvestmentRecord(side=SELL, realized_pnl!=NULL)`

2. `test_sell_rejects_when_insufficient_position`
- 卖出量 > 持仓量
- 期望：409，所有表回滚

3. `test_sell_all_clears_position_cost_fields`
- 全部卖出
- 断言：`quantity=0 && avg_cost=0 && cost_total=0`

4. `test_sell_currency_mismatch_rejected`
- 标的币种和账户币种不匹配
- 期望：409

5. `test_sell_forbidden_on_other_users_account`
- 期望：403

## 5.3 并发一致性用例（新增）

1. `test_concurrent_sell_same_position_only_one_succeeds`
- 初始持仓仅够一次卖出
- 两并发请求同时卖出同等数量
- 期望：1 成功 + 1 失败，不出现负持仓

2. `test_concurrent_buy_and_sell_serialized_consistently`
- 同账户同标的并发一买一卖
- 断言最终 `balance/quantity/cost_total` 与可串行结果一致

3. `test_position_create_race_still_single_row`
- 并发首次交易同标的
- 断言 `Position(user,instrument)` 仍唯一

## 5.4 跨模块一致性用例（高价值）

1. `test_reverse_trade_transaction_should_be_blocked_or_consistent`
- 对投资买入产生的 `Transaction` 调用 `/api/user/transactions/{id}/reverse/`
- 期望（按设计二选一）：
  - 被禁止；或
  - 自动同步回滚投资侧（持仓/记录）

2. `test_trade_atomicity_when_record_create_fails`
- 通过 mock 让 `InvestmentRecord.objects.create` 抛异常
- 期望：账户余额和持仓都回滚

## 6. 实施顺序建议

1. 先提取公共交易服务，避免买入卖出逻辑分叉
2. 落地 `sell` 接口与测试
3. 修复高风险点：小额舍入 + reverse 一致性
4. 最后再考虑统一 `trades` 接口与幂等键

## 7. 本文档对应代码位置（便于对照）

- `investment/models.py`
- `investment/serializers.py`
- `investment/views.py`
- `investment/urls.py`
- `investment/tests.py`
- `accounts/models.py`
- `accounts/views.py`
- `accounts/serializers.py`
