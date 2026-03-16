from django import VERSION as DJANGO_VERSION
from django.db import models
from django.db.models import Q


# 兼容不同 Django 版本的 `CheckConstraint` 参数差异。
def check_constraint(*, expr: Q, name: str) -> models.CheckConstraint:
    if DJANGO_VERSION >= (5, 1):
        return models.CheckConstraint(condition=expr, name=name)
    return models.CheckConstraint(check=expr, name=name)
