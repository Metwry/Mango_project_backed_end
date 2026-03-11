# Data Directory / 数据目录

## 中文

- 定位：存放运行期需要的静态市场日历数据。
- 当前内容：`market_calendars/` 下维护 CN、HK、US 市场的 2026 和 2027 交易日 CSV。
- 使用方式：`market` 模块在行情同步和交易日判断时读取这些文件。
- 注意事项：如果交易日历缺失，行为受 `MARKET_CALENDAR_REQUIRED` 和 `MARKET_PULL_FALLBACK_ON_MISSING_CALENDAR` 控制。

## English

- Role: stores static market calendar data required at runtime.
- Current content: CSV trading calendars for CN, HK, and US markets for 2026 and 2027 under `market_calendars/`.
- Usage: the `market` module reads these files for trading-day checks and quote synchronization.
- Notes: missing-calendar behavior is controlled by `MARKET_CALENDAR_REQUIRED` and `MARKET_PULL_FALLBACK_ON_MISSING_CALENDAR`.
