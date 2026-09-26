# 药品生产偏差与批次放行系统

Python 标准库 + SQLite。批次可关联关键/一般偏差、检验复测、返工、供应商变更和稳定性数据。质量人员可以拒绝、再取样、有条件放行或正式放行；关键偏差始终阻止正式放行，修改必须携带当前批次修订号。

## 代码结构

- `storage.py`：SQLite 连接、建表、旧库自动迁移和审计日志。
- `service.py`：批次、偏差、检验、返工与放行决定的领域规则。
- `api.py`：HTTP 路由、请求解析和进程入口。
- `app.py`：兼容入口，转发到上述模块，原有启动方式不变。

## 运行

```bash
python3 app.py --init --seed
python3 app.py
```

默认端口 `8214`。身份通过 `X-Actor` 与 `X-Role` 模拟，角色为 `operator`、`inspector`、`lab`、`qa`。工厂人员只能修改本工厂批次。可用 `--port`、`--db` 覆盖。

## 放行门禁规则

- 偏差到期日是真实门禁：未关闭偏差一旦超期（以延期后的新日期为准），正式放行和有条件放行都会被拒绝，并返回仍需处理的偏差编号，不能先放行再补调查。
- 延期（例外批准）只能在到期前提交，必须说明原因；原到期日保留在 `due_at`，新日期记录在 `exception_until`。已经超期的偏差不能再改到未来。
- 关闭偏差必须填写调查证据摘要，系统同时保存关闭人和关闭时间。
- 旧版本数据库启动时自动补齐新列，既有批次和记录继续可用。

## 主要接口

- `POST /api/factories`、`POST /api/batches`：登记工厂和批次。
- `POST /api/batches/{id}/deviations`、`POST /api/deviations/{id}/close`：记录和关闭偏差（关闭需 `corrective_action` 和 `evidence`）。
- `POST /api/deviations/{id}/exception`：到期前为一般偏差申请延期（`reason` + `until`）。
- `POST /api/batches/{id}/tests`：记录检验和复测轮次。
- `POST /api/batches/{id}/rework`、`POST /api/rework/{id}/complete`：计划和完成返工。
- `POST /api/batches/{id}/supplier-changes`、`POST /api/batches/{id}/stability`：关联供应链和稳定性记录。
- `POST /api/batches/{id}/decide`：质量决定，支持并发修订号检查；超期未关闭偏差会返回偏差编号并阻止放行。
- `GET /api/batches/{id}`、`GET /api/state`、`GET /api/health`：详情、状态和健康检查。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

当前为原型：规则以最新检验项目、未关闭偏差、到期日门禁和例外有效期为核心，不等同于真实 GMP 质量体系、电子签名、验证或监管提交规范。
