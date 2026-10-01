"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

from typing import Any

from app.seed import SEED_ROWS

MODULE_LABELS = {
    "register": "使用登记",
    "boiler": "锅炉管理",
    "pressurevessel": "压力容器",
    "pipeline": "压力管道",
    "elevator": "电梯管理",
    "crane": "起重机械",
    "forklift": "场车管理",
    "inspection": "定期检验",
    "maintenance": "维保记录",
    "hazard": "隐患排查",
    "accident": "事故管理",
    "operator": "作业人员",
    "training": "培训考核",
    "safetyvalve": "安全阀校验",
    "gauge": "压力表检定",
    "sparepart": "备件管理",
    "emergency": "应急演练",
    "energyeff": "能效监测",
    "archive": "档案管理",
    "contract": "维保合同",
    "fault": "设备故障报送",
}


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": MODULE_LABELS.get(name, name),
                "key": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
