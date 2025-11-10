"""
任务模型定义
定义任务的状态和数据结构
"""
import time
from typing import Optional, Callable
from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"          # 等待执行
    SUBMITTED = "submitted"      # 已提交
    PROCESSING = "processing"    # 正在执行
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"            # 执行失败
    
    def is_terminal(self) -> bool:
        """判断是否为终态"""
        return self in (TaskStatus.COMPLETED, TaskStatus.FAILED)
    
    def is_active(self) -> bool:
        """判断是否为活跃状态(未完成)"""
        return not self.is_terminal()


@dataclass
class TaskRequest:
    """任务请求数据模型"""
    task_id: str
    client_id: str
    prompt: dict
    output_base64: bool = False
    output_oss: bool = False
    callback: Optional[Callable] = None
    status: TaskStatus = TaskStatus.PENDING
    
    # 时间戳
    create_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    
    def update_status(self, new_status: TaskStatus) -> bool:
        """
        更新任务状态,包含状态转换校验
        
        Returns:
            bool: 状态是否成功更新
        """
        # 终态不允许再次更新
        if self.status.is_terminal():
            return False
        
        # 状态转换逻辑
        valid_transitions = {
            TaskStatus.PENDING: {TaskStatus.SUBMITTED, TaskStatus.PROCESSING, TaskStatus.FAILED},
            TaskStatus.SUBMITTED: {TaskStatus.PROCESSING, TaskStatus.FAILED},
            TaskStatus.PROCESSING: {TaskStatus.COMPLETED, TaskStatus.FAILED},
        }
        
        if new_status not in valid_transitions.get(self.status, set()):
            return False
        
        # 更新状态和时间戳
        self.status = new_status
        
        if new_status == TaskStatus.PROCESSING and self.started_at is None:
            self.started_at = time.time()
        elif new_status.is_terminal() and self.completed_at is None:
            self.completed_at = time.time()
        
        return True
    
    def get_elapsed_time(self) -> Optional[float]:
        """获取任务执行耗时(秒)"""
        if not self.started_at:
            return None
        
        end_time = self.completed_at or time.time()
        return end_time - self.started_at
    
    def get_age(self) -> float:
        """获取任务创建以来的时长(秒)"""
        return time.time() - self.create_at
    
    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            'task_id': self.task_id,
            'client_id': self.client_id,
            'status': self.status.value,
            'create_at': self.create_at,
            'started_at': self.started_at,
            'completed_at': self.completed_at,
            'elapsed_time': self.get_elapsed_time(),
            'age': self.get_age()
        }

