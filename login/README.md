# Login Module / 认证模块

## 中文

- 定位：提供邮箱注册、验证码发送、密码重置、用户名维护和登录鉴权。
- 核心能力：登录接口统一使用 `username` 字段，值既可以是真实用户名也可以是邮箱；注册和重置密码都需要邮箱验证码，登录成功后返回 JWT。
- 主要接口：`/api/login/`、`/api/register/email/code/`、`/api/register/email/`、`/api/password/reset/code/`、`/api/password/reset/`、`/api/user/profile/username/`。
- 依赖关系：依赖 Django 内置用户模型、SMTP 邮件配置，以及 `rest_framework_simplejwt`。

## English

- Role: provides email registration, verification code delivery, password reset, username updates, and login.
- Core capability: the login endpoint always uses the `username` field, whose value can be either a real username or an email; registration and password reset require email codes, and successful login returns JWT.
- Main APIs: `/api/login/`, `/api/register/email/code/`, `/api/register/email/`, `/api/password/reset/code/`, `/api/password/reset/`, `/api/user/profile/username/`.
- Dependencies: relies on Django's built-in user model, SMTP configuration, and `rest_framework_simplejwt`.
