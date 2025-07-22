#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
进度条测试脚本
"""

import time
import threading
import logging
from image_filter_main import BottomProgressBar, SafeLogHandler

def test_progress_bar():
    """测试进度条功能"""
    print("🧪 测试底部固定进度条")
    print("=" * 50)
    
    # 创建进度条
    progress_bar = BottomProgressBar()
    
    # 设置日志
    logger = logging.getLogger("test")
    logger.setLevel(logging.INFO)
    
    # 清除现有处理器
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # 添加兼容进度条的处理器
    handler = SafeLogHandler(progress_bar)
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
    
    # 启动进度条
    progress_bar.start()
    
    total = 50
    
    def simulate_work():
        """模拟工作线程"""
        for i in range(total):
            time.sleep(0.2)  # 模拟处理时间
            
            # 模拟日志输出
            if i % 5 == 0:
                logger.info(f"处理第 {i+1} 个任务")
            
            # 更新进度条
            speed = (i + 1) / ((i + 1) * 0.2)
            eta = (total - i - 1) * 0.2 / 60
            progress_bar.update(i + 1, total, speed, eta)
    
    def log_worker():
        """模拟其他日志输出"""
        for i in range(10):
            time.sleep(1)
            logger.warning(f"这是一条警告日志 #{i+1}")
    
    # 启动工作线程
    work_thread = threading.Thread(target=simulate_work)
    log_thread = threading.Thread(target=log_worker)
    
    work_thread.start()
    log_thread.start()
    
    work_thread.join()
    log_thread.join()
    
    # 停止进度条
    progress_bar.stop()
    
    print("✅ 测试完成！")
    print("进度条应该始终显示在底部，不影响日志输出")

if __name__ == "__main__":
    test_progress_bar()
