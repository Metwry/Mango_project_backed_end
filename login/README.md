# Login Module / 认证模块

## 中文

- 定位：提供邮箱注册、验证码发送、密码重置、用户名维护和登录鉴权。
- 核心能力：支持用户名或邮箱登录，注册和重置密码都需要邮箱验证码，登录成功后返回 JWT。
- 主要接口：`/api/login/`、`/api/register/email/code/`、`/api/register/email/`、`/api/password/reset/code/`、`/api/password/reset/`、`/api/user/profile/username/`。
- 依赖关系：依赖 Django 内置用户模型、SMTP 邮件配置，以及 `rest_framework_simplejwt`。

## English

- Role: provides email registration, verification code delivery, password reset, username updates, and login.
- Core capability: supports login by username or email, requires email codes for registration and password reset, and issues JWT tokens on success.
- Main APIs: `/api/login/`, `/api/register/email/code/`, `/api/register/email/`, `/api/password/reset/code/`, `/api/password/reset/`, `/api/user/profile/username/`.
- Dependencies: relies on Django's built-in user model, SMTP configuration, and `rest_framework_simplejwt`.
