"""
Task 模型定义
定义任务的状态枚举和数据结构
"""
import time
from typing import Optional
from dataclasses import dataclass
from enum import Enum


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"          # 等待执行
    RUNNING = "running"          # 正在执行
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"            # 执行失败
    
    def is_terminal(self) -> bool:
        """判断是否为终态"""
        return self in (TaskStatus.COMPLETED, TaskStatus.FAILED)
    
    def is_active(self) -> bool:
        """判断是否为活跃状态(未完成)"""
        return not self.is_terminal()


@dataclass
class Task:
    """任务数据模型"""
    task_id: str  # 任务ID，同时也作为 ComfyUI history 的 prompt_id
    client_id: str
    prompt_body: dict
    user_id: str  # 任务所属用户ID
    status: TaskStatus = TaskStatus.PENDING
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
            TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.FAILED},
            TaskStatus.RUNNING: {TaskStatus.COMPLETED, TaskStatus.FAILED},
        }
        
        if new_status not in valid_transitions.get(self.status, set()):
            return False
        
        # 更新状态和时间戳
        self.status = new_status
        
        # 设置 completed_at：当状态变为终态时
        if new_status.is_terminal() and self.completed_at is None:
            self.completed_at = time.time()
        
        return True

