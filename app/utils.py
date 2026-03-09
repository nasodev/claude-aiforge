def safe_int(val, default: int = 0) -> int:
    """값을 int로 안전하게 변환. str/None/float 등 모두 처리."""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default
