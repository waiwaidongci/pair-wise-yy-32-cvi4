#!/usr/bin/env python3
"""Pharmaceutical batch deviation, rework and release decision service.

兼容入口：实现已拆分为 storage（存储）、service（领域服务）、api（接口）三个模块。
"""
from api import Handler, main, run
from service import BatchService
from storage import ApiError, Store

__all__ = ["ApiError", "BatchService", "Handler", "Store", "main", "run"]

if __name__ == "__main__":
    main()
