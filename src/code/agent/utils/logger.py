from datetime import datetime


def log(level, message):
    """统一的日志输出函数，带时间戳（精确到毫秒）"""
    now = datetime.now()
    timestamp = now.strftime('%Y-%m-%d %H:%M:%S')
    milliseconds = now.microsecond // 1000
    print(f"[{timestamp}.{milliseconds:03d}] [{level}] {message}")

