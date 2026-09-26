#!/usr/bin/env python3
"""Pharmaceutical batch deviation, rework and release decision service.

入口模块：业务代码拆分为 storage（存储）、service（领域服务）、api（接口）三个文件，
此处保留旧的导入路径并负责启动。
"""
from api import main, run
from service import BatchService
from storage import ApiError, Store

__all__ = ["ApiError", "BatchService", "Store", "main", "run"]

if __name__ == "__main__":
    main()
