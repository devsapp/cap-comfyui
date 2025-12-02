#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在 Dockerfile 中安装 ComfyUI 自定义节点依赖的脚本
复用 PIPInstaller 的健壮安装逻辑
"""

import os
import sys

# 设置必要的环境变量（如果未设置）
if not os.getenv('COMFYUI_DIR'):
    os.environ['COMFYUI_DIR'] = '/root/comfyui'
if not os.getenv('VENV_DIR'):
    os.environ['VENV_DIR'] = '/root/venv'
if not os.getenv('WORK_DIR'):
    os.environ['WORK_DIR'] = '/root'
if not os.getenv('BACKEND_TYPE'):
    os.environ['BACKEND_TYPE'] = 'comfyui'

# 添加 agent 代码路径到 sys.path
agent_code_path = '/root/agent'
if agent_code_path not in sys.path:
    sys.path.insert(0, agent_code_path)

# 确保可以导入 agent 的模块
# 添加 agent 的子目录到 sys.path
for subdir in ['services', 'utils']:
    subdir_path = os.path.join(agent_code_path, subdir)
    if os.path.exists(subdir_path) and subdir_path not in sys.path:
        sys.path.insert(0, subdir_path)

try:
    from services.pip.pip_installer import PIPInstaller
    import constants
    
    print("=" * 60)
    print("开始安装 ComfyUI 自定义节点依赖")
    print("=" * 60)
    
    # 创建安装器实例
    installer = PIPInstaller()
    
    # 安装所有自定义节点的依赖
    # nodes_map=None 表示安装所有可用的节点
    # timeout 使用默认值（10分钟）
    result = installer.install_all(timeout=constants.DEFAULT_INSTALL_TIMEOUT, nodes_map=None)
    
    # 输出安装结果
    print("\n" + "=" * 60)
    print("安装完成，结果摘要：")
    print("=" * 60)
    
    # 依赖安装结果
    if result.get('dependencies'):
        dep_result = result['dependencies']
        print(f"\n依赖安装: {'✅ 成功' if dep_result.get('success') else '❌ 失败'}")
        if dep_result.get('error_msg'):
            print(f"错误信息: {dep_result['error_msg']}")
        print(f"耗时: {dep_result.get('duration', 0):.1f}秒")
    
    # 脚本安装结果
    scripts = result.get('scripts', [])
    if scripts:
        success_count = sum(1 for s in scripts if s.get('success'))
        total_count = len(scripts)
        print(f"\ninstall.py 脚本: {success_count}/{total_count} 成功")
        for script in scripts:
            status = "✅" if script.get('success') else "❌"
            print(f"  {status} {script.get('node_name', 'unknown')}: {script.get('duration', 0):.1f}秒")
            if script.get('error_msg'):
                print(f"    错误: {script['error_msg']}")
    
    # 检查是否有失败
    dep_success = result.get('dependencies', {}).get('success', True)
    script_success = all(s.get('success', True) for s in scripts)
    
    if not dep_success or not script_success:
        print("\n⚠️  警告: 部分安装失败，但构建将继续")
        sys.exit(0)  # 不中断构建，只输出警告
    else:
        print("\n✅ 所有依赖安装成功")
        sys.exit(0)
        
except ImportError as e:
    print(f"❌ 导入错误: {e}")
    print("请确保 agent 代码已正确复制到 /root/agent")
    sys.exit(1)
except Exception as e:
    print(f"❌ 安装过程中发生错误: {e}")
    import traceback
    traceback.print_exc()
    # 不中断构建，只输出错误
    sys.exit(0)

