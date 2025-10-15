# 第一步：全局替换 print 函数（必须在所有其他导入之前）
import builtins
from datetime import datetime

_original_print = builtins.print

def timestamped_print(*args, **kwargs):
    """带时间戳的 print 函数"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    message = ' '.join(str(arg) for arg in args)
    timestamped_message = f"{timestamp} {message}"
    _original_print(timestamped_message, **kwargs)

builtins.print = timestamped_print

# 第二步：初始化日志系统
from utils.logger import init_logging
init_logging()

# 第三步：导入其他模块
from routes.routes import Routes

r = Routes()

if __name__ == "__main__":
    r.app.run(debug=False, host="0.0.0.0", port=9000)
