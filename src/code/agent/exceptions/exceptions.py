class CustomError(Exception):
    """自定义异常基类"""
    def __init__(self, code=500, message=""):
        self.code = code
        self.message = message
        super().__init__(self.message)


class StateTransitionError(CustomError):
    def __init__(self, from_state, to_state):
        msg = f"Illegal state transition: {from_state} -> {to_state}"
        super().__init__(message=msg, code=409)


class InternalError(CustomError):
    """内部错误 - 系统内部操作失败"""
    def __init__(self, message: str, code: int = 500):
        super().__init__(code=code, message=message)


# ========== 任务管理相关异常 ==========

class TaskError(CustomError):
    """任务管理异常基类"""
    def __init__(self, message: str, error_code: str = "task_error", code: int = 500):
        self.error_code = error_code
        super().__init__(code=code, message=message)
    
    def to_dict(self):
        return {
            "type": "error",
            "error_code": self.error_code,
            "error_message": self.message
        }


class ConfigurationError(TaskError):
    """配置错误"""
    def __init__(self, message: str):
        super().__init__(message=message, error_code="configuration_error", code=500)


class InvalidRequestError(TaskError):
    """无效请求"""
    def __init__(self, message: str, error_code: str = "invalid_request_error"):
        super().__init__(message=message, error_code=error_code, code=400)


class TaskQueueFullError(TaskError):
    """任务队列已满 - 系统达到最大并发限制"""
    def __init__(self, message: str, active_tasks: int = None, max_tasks: int = None):
        super().__init__(message=message, error_code="queue_full", code=429)
        self.active_tasks = active_tasks
        self.max_tasks = max_tasks


class WorkerExecutionError(TaskError):
    """Worker执行异常 - Worker执行任务时发生的错误（网络、超时、非2xx响应等）"""
    def __init__(self, message: str, status_code: int = 500, 
                 error_code: str = "worker_execution_error", original_response: dict = None):
        super().__init__(message=message, error_code=error_code, code=status_code)
        self.original_response = original_response
