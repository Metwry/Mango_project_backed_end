# Data Directory / 数据目录

## 中文

- 定位：存放运行期需要的静态资源文件。
- 当前内容：不再维护市场交易日 CSV，市场开市判断已改为运行时直接使用 `exchange_calendars`。
- 使用方式：`market` 模块仍会读取这里的其他静态资源，但不再依赖市场日历文件。

## English

- Role: stores static resources required at runtime.
- Current content: market trading CSV calendars are no longer stored here; market-open checks now use `exchange_calendars` directly at runtime.
- Usage: the `market` module may still read other static resources here, but it no longer depends on market-calendar files.
