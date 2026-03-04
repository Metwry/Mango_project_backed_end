# 账户与投资账户生命周期测试用例（V1）

## 1. 目标与范围

本文件覆盖以下核心业务链路，并以“真实用户行为”组织测试：

1. 普通账户（现金/银行卡/证券/加密）增删改查
2. 普通账户记账与撤销
3. 投资账户自动创建、自动归档、再次激活
4. 账户与交易/持仓/投资记录的关联一致性

---

## 2. 关联关系设计（当前实现）

## 2.1 核心关系

1. `accounts.Accounts` 是资金账户主表
2. `accounts.Transaction.account` 使用 `on_delete=PROTECT`
3. `investment.InvestmentRecord.cash_account` 使用 `on_delete=PROTECT`
4. `snapshot.AccountSnapshot.account` / `snapshot.PositionSnapshot.account` 使用 `on_delete=PROTECT`

## 2.2 删除策略

1. 账户删除为“软删除”：`status=ARCHIVED`
2. 不做物理删除，避免审计链路断裂
3. 账户列表默认只返回 `ACTIVE`，可用 `include_archived=1` 查看归档账户

## 2.3 投资账户策略

1. 首次买入后自动创建投资账户（`name=投资账户`）
2. 卖出到零持仓后，投资账户自动归档（不是物理删除）
3. 后续再次买入时，优先复用并激活已归档投资账户（保留同一账户 ID）
4. 若投资账户仍有持仓，手工删除会被拒绝（409）
5. 投资买卖产生的资金流水 `Transaction.source=investment`，不允许从活动记录接口撤销
6. 投资交易历史通过独立只读接口查询：`GET /api/investment/history/`

---

## 3. 用户模拟流程

## 3.1 普通账户流程

1. 用户创建普通账户（例如 `Cash CNY`）
2. 用户新增支出交易，账户余额下降
3. 用户撤销该交易，余额恢复，原交易标记 `reversed_at`
4. 用户删除该账户，系统将其归档，交易历史仍保留
5. 用户默认列表看不到该账户，带 `include_archived=1` 可看到

## 3.2 投资账户流程

1. 用户首次买入股票，系统自动创建投资账户并维护估值余额
2. 用户卖出全部持仓，持仓记录清零并删除，投资账户归档
3. 用户再次买入，系统激活同一投资账户（ID 不变）
4. 若投资账户仍有持仓，用户手工删除该账户返回 409

---

## 4. 测试矩阵（场景 -> 预期）

1. 场景：普通账户改币种  
预期：按 USD 汇率缓存换算余额；缺汇率时返回 400，余额不变
2. 场景：普通账户新增交易  
预期：生成活动记录，账户余额按 `amount` 变更
3. 场景：普通账户撤销交易  
预期：生成反向交易，原交易打 `reversed_at`
4. 场景：普通账户删除  
预期：账户 `status=ARCHIVED`，关联交易仍可查询
5. 场景：投资账户首次买入  
预期：自动创建投资账户（ACTIVE）
6. 场景：卖出最后持仓  
预期：持仓消失，投资账户变 `ARCHIVED`
7. 场景：归档后再次买入  
预期：复用同一投资账户并激活（ID 不变）
8. 场景：投资账户存在持仓时手工删除  
预期：返回 409，账户保持 ACTIVE
9. 场景：并发撤销同一交易  
预期：仅一笔撤销成功，另一笔 400
10. 场景：并发卖出最后持仓  
预期：仅一笔卖出成功，另一笔 409，系统状态一致
11. 场景：尝试撤销投资买卖生成的流水  
预期：返回 400，余额不回滚
12. 场景：查询投资交易历史接口  
预期：返回只读列表（含标的/资金账户/现金流），DELETE 返回 405

---

## 5. 自动化测试映射

## 5.1 `accounts/tests.py`

1. `test_transaction_create_and_reverse`
2. `test_account_currency_change_converts_balance_by_fx_rate`
3. `test_account_currency_change_fails_when_rate_pair_missing`
4. `test_delete_normal_account_archives_and_keeps_transactions`
5. `test_delete_investment_account_blocked_when_has_positions`
6. `test_delete_investment_account_without_positions_archives`
7. `test_concurrent_reverse_only_one_succeeds`

## 5.2 `investment/tests.py`

1. `test_sell_all_deletes_position_and_archives_investment_account`
2. `test_buy_after_full_sell_reuses_archived_investment_account`
3. `test_concurrent_first_buy_only_one_investment_account`
4. `test_concurrent_sell_last_position_keeps_state_consistent`
5. `test_cannot_reverse_investment_generated_cash_transaction`
6. `test_history_query_returns_read_only_investment_records`
5. 其余买卖与投资账户变更限制测试

---

## 6. 接口级检查点

1. `DELETE /api/user/accounts/{id}/`  
返回 `204` 表示归档成功，不代表物理删除
2. `GET /api/user/accounts/`  
默认不返回归档账户
3. `GET /api/user/accounts/?include_archived=1`  
可返回归档账户
4. `POST /api/user/transactions/{id}/reverse/`  
重复撤销应失败；若是投资交易流水，直接拒绝撤销
5. `POST /api/investment/buy/`  
触发投资账户自动创建/激活
6. `POST /api/investment/sell/`  
卖空后触发投资账户自动归档
7. `GET /api/investment/history/`  
查询只读投资交易历史（不提供删除接口）

---

## 7. 执行命令

Windows（PowerShell / CMD）：

```powershell
py manage.py test accounts.tests investment.tests -v 1 --noinput --keepdb
```

Linux/macOS（bash/zsh）：

```bash
python3 manage.py test accounts.tests investment.tests -v 1 --noinput --keepdb
```

---

## 8. 本轮回归结果

1. 用例数量：`17`
2. 结果：`OK`
3. 说明：包含并发撤销、并发卖出、普通账户归档删除、投资账户归档/再激活链路
