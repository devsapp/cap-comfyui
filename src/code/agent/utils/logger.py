from datetime import datetime
import os


# 日志级别定义（数字越小优先级越高）
LOG_LEVELS = {
    'ERROR': 0,
    'WARNING': 1,
    'INFO': 2,
    'DEBUG': 3
}

# 从环境变量读取日志级别，默认为 INFO
DEFAULT_LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
CURRENT_LOG_LEVEL = LOG_LEVELS.get(DEFAULT_LOG_LEVEL, LOG_LEVELS['INFO'])


def log(level, message):
    """
    统一的日志输出函数，带时间戳（精确到毫秒）
    
    支持日志级别控制：
    - ERROR: 错误信息（总是输出）
    - WARNING: 警告信息
    - INFO: 一般信息（默认级别）
    - DEBUG: 调试信息（需要设置 LOG_LEVEL=DEBUG 环境变量）
    
    Args:
        level: 日志级别 (ERROR/WARNING/INFO/DEBUG)
        message: 日志消息
    """
    level_upper = level.upper()
    
    # 检查日志级别是否应该输出
    if LOG_LEVELS.get(level_upper, LOG_LEVELS['INFO']) > CURRENT_LOG_LEVEL:
        return
    
    now = datetime.now()
    timestamp = now.strftime('%Y-%m-%d %H:%M:%S')
    milliseconds = now.microsecond // 1000
    print(f"[{timestamp}.{milliseconds:03d}] [{level_upper}] {message}")


def set_log_level(level):
    """
    动态设置日志级别
    
    Args:
        level: 日志级别 (ERROR/WARNING/INFO/DEBUG)
    """
    global CURRENT_LOG_LEVEL
    level_upper = level.upper()
    if level_upper in LOG_LEVELS:
        CURRENT_LOG_LEVEL = LOG_LEVELS[level_upper]
        log("INFO", f"Log level changed to: {level_upper}")
    else:
        log("WARNING", f"Invalid log level: {level}, keeping current level")


def get_log_level():
    """
    获取当前日志级别
    
    Returns:
        str: 当前日志级别名称
    """
    for level_name, level_value in LOG_LEVELS.items():
        if level_value == CURRENT_LOG_LEVEL:
            return level_name
    return "INFO"

