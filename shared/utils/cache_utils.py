# 从缓存载荷中安全提取 `data` 字典，结构不合法时返回空字典。
def safe_payload_data(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else {}
