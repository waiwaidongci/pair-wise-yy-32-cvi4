# 药品生产偏差与批次放行系统

Python 标准库 + SQLite。批次可关联关键/一般偏差、检验复测、返工、供应商变更和稳定性数据。质量人员可以拒绝、再取样、有条件放行或正式放行；关键偏差始终阻止正式放行，修改必须携带当前批次修订号。

偏差到期日是真实的放行门禁：未关闭偏差一旦超期，正式放行和有条件放行都会被拒绝，并在响应的 `overdue_deviations` 中返回仍需处理的偏差编号，不能先放行再补调查。延期只能在到期前提交，需说明原因，系统保留原到期日（`original_due_at`）和新到期日；已经超期的偏差不能改到未来日期。关闭偏差必须填写调查证据摘要，并与关闭人、关闭时间一起保存。

## 代码结构

- `storage.py`：SQLite 连接、建表和旧数据库的幂等列迁移（旧库升级后既有批次和记录继续可用）。
- `service.py`：批次、偏差、检验、返工和放行决策的领域规则。
- `api.py`：HTTP 路由、请求解析和错误响应。
- `app.py`：入口，兼容旧的导入路径（`from app import ApiError, BatchService, Store`）。

## 运行

```bash
python3 app.py --init --seed
python3 app.py
```

默认端口 `8214`。身份通过 `X-Actor` 与 `X-Role` 模拟，角色为 `operator`、`inspector`、`lab`、`qa`。工厂人员只能修改本工厂批次。可用 `--port`、`--db` 覆盖。

## 主要接口

- `POST /api/factories`、`POST /api/batches`：登记工厂和批次。
- `POST /api/batches/{id}/deviations`、`POST /api/deviations/{id}/close`：记录和关闭偏差，关闭需 `corrective_action` 和 `evidence_summary`。
- `POST /api/deviations/{id}/extend`：到期前延期，需 `reason` 和更晚的 `new_due_at`，保留原到期日。
- `POST /api/deviations/{id}/exception`：为一般偏差批准有期限例外。
- `POST /api/batches/{id}/tests`：记录检验和复测轮次。
- `POST /api/batches/{id}/rework`、`POST /api/rework/{id}/complete`：计划和完成返工。
- `POST /api/batches/{id}/supplier-changes`、`POST /api/batches/{id}/stability`：关联供应链和稳定性记录。
- `POST /api/batches/{id}/decide`：质量决定，支持并发修订号检查；超期未关闭偏差会以 409 和 `overdue_deviations` 编号列表阻止放行。
- `GET /api/batches/{id}`、`GET /api/state`、`GET /api/health`：详情、状态和健康检查。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

当前为原型：规则以最新检验项目、未关闭偏差、偏差到期日和例外有效期为核心，不等同于真实 GMP 质量体系、电子签名、验证或监管提交规范。
