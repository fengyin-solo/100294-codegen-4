"""设备故障报送业务规则：单向流水、去重开单、断点续处置、重复故障归集与台账同步。

流水口径：待受理 → 已受理 → 处理中 → 待复核 → 已收口，只允许一步一步往前走；
处理中不提交复核不允许直接收口，已受理的单不允许退回待受理。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "faultreport"
LEDGER_MODULE = "register"
REQUIRED_FIELDS = ["设备编号", "设备名称", "故障类别", "故障描述", "报修人", "设备责任人"]
STATUS_ORDER = ["待受理", "已受理", "处理中", "待复核", "已收口"]
ACTION_RULES = {"受理": "已受理", "开始处理": "处理中", "提交复核": "待复核", "复核收口": "已收口"}
ACTION_STAMPS = {"受理": ("受理人", "受理时间"), "开始处理": ("处理人", "处理时间"), "提交复核": ("复核人", "复核时间")}
STEP_STAGE = {"受理": "已受理", "处理": "处理中", "复核": "待复核"}
RECURRING_WINDOW_DAYS = 30
TIME_FMT = "%Y-%m-%d %H:%M"


def _now() -> str:
    return datetime.now().strftime(TIME_FMT)


def _parse_time(value: Any) -> datetime | None:
    try:
        return datetime.strptime(str(value), TIME_FMT)
    except (TypeError, ValueError):
        return None


class FaultReportService:
    """故障报送单的开单、流转、处置记录与看板口径。"""

    # ---- 查询：列表、明细、重复故障 ----
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        device: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = list(store.rows(MODULE))
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("故障单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if device:
            rows = [row for row in rows if device in str(row.get("设备编号", ""))]
        self._mark_recurring(rows)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        self._mark_recurring([entry])
        return entry

    def recurring_groups(self) -> list[dict[str, Any]]:
        """一个月内重复冒出来的故障：按设备+故障类别归组，单独拎出来。"""
        groups: list[dict[str, Any]] = []
        for key in sorted(self._recurring_keys()):
            device, category = key
            tickets = [
                row for row in store.rows(MODULE)
                if str(row.get("设备编号", "")) == device and str(row.get("故障类别", "")) == category
            ]
            tickets.sort(key=lambda row: str(row.get("报送时间", "")))
            groups.append({
                "设备编号": device,
                "设备名称": tickets[0].get("设备名称", ""),
                "故障类别": category,
                "重复次数": len(tickets),
                "最近报送": tickets[-1].get("报送时间", ""),
                "涉及工单": [row.get("故障单号", "") for row in tickets],
                "未闭环": any(row.get("status") != STATUS_ORDER[-1] for row in tickets),
            })
        return groups

    # ---- 开单：同设备同故障只留未闭环那张 ----
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, "missing"
        device = str(values.get("设备编号")).strip()
        category = str(values.get("故障类别")).strip()
        for row in store.rows(MODULE):
            if (
                str(row.get("设备编号", "")) == device
                and str(row.get("故障类别", "")) == category
                and row.get("status") != STATUS_ORDER[-1]
            ):
                return row, [], "duplicate"
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry["故障单号"] = f"FAUL-{entry['id']:04d}"
        for field in REQUIRED_FIELDS:
            entry[field] = str(values.get(field)).strip()
        entry["报送时间"] = str(values.get("报送时间") or "").strip() or _now()
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["受理人"] = None
        entry["受理时间"] = None
        entry["处理人"] = None
        entry["处理时间"] = None
        entry["复核人"] = None
        entry["复核时间"] = None
        entry["收口时间"] = None
        entry["处置记录"] = {}
        entry["处置结论"] = ""
        entry["台账已同步"] = False
        rows.append(entry)
        return entry, [], "created"

    # ---- 流转：只能往前走，处理中未经复核不许收口 ----
    def run_action(self, entry_id: int, action: str, operator: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"故障工单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于故障报送可执行范围"
        current = str(entry.get("status", ""))
        target = ACTION_RULES[action]
        if current not in STATUS_ORDER:
            return None, f"当前状态「{current}」不在流水序列里，请联系管理员核对"
        step = STATUS_ORDER.index(target) - STATUS_ORDER.index(current)
        if step <= 0:
            return None, f"流水只往前走：「{current}」不允许回到「{target}」"
        if step > 1:
            if current == "处理中" and target == "已收口":
                return None, "处理中的故障单必须先提交复核，不允许直接收口"
            return None, f"流水只能一步一步走：「{current}」不能直接跳到「{target}」"
        if action == "复核收口" and not str(entry.get("处置结论") or "").strip():
            return None, "收口前必须先由本设备责任人填写处置结论"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        stamp = ACTION_STAMPS.get(action)
        if stamp:
            entry[stamp[0]] = operator or "未署名"
            entry[stamp[1]] = _now()
        message = f"故障工单已{action}"
        if action == "复核收口":
            entry["收口时间"] = _now()
            if self._sync_ledger(entry):
                message += "，处置结论已同步设备台账"
            else:
                message += "，但未找到对应设备台账，结论待补录"
        return entry, message

    # ---- 处置记录：断点续走，已填写的不许被顶掉 ----
    def save_step(self, entry_id: int, step: str, content: str, operator: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"故障工单 {entry_id} 不存在或已归档"
        if step not in STEP_STAGE:
            return None, f"处置步骤「{step}」不在受理、处理、复核范围内"
        if not content.strip():
            return None, "处置记录内容不能为空"
        current = STATUS_ORDER.index(str(entry.get("status", STATUS_ORDER[0])))
        if current < STATUS_ORDER.index(STEP_STAGE[step]):
            return None, f"工单还没流转到「{step}」这一步，先完成前面的动作再补记录"
        records = entry.setdefault("处置记录", {})
        if step in records:
            return None, f"「{step}」处置记录已填写，不允许覆盖，可从断掉的下一步接着走"
        records[step] = {"content": content.strip(), "operator": operator or "未署名", "time": _now()}
        return entry, f"「{step}」处置记录已保存"

    # ---- 处置结论：只有本设备的责任人能改 ----
    def save_conclusion(self, entry_id: int, operator: str, conclusion: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"故障工单 {entry_id} 不存在或已归档"
        owner = str(entry.get("设备责任人") or "").strip()
        if not owner:
            return None, "该工单未登记设备责任人，处置结论暂不可修改"
        if operator.strip() != owner:
            return None, f"处置结论只能由本设备责任人「{owner}」修改，其他班组只能查看"
        if not conclusion.strip():
            return None, "处置结论不能为空"
        entry["处置结论"] = conclusion.strip()
        message = "处置结论已保存"
        if entry.get("status") == STATUS_ORDER[-1]:
            self._sync_ledger(entry)
            message += "，已重新同步设备台账"
        return entry, message

    # ---- 看板：直接从明细现算，保证与明细同步 ----
    def board(self) -> dict[str, Any]:
        rows = list(store.rows(MODULE))
        self._mark_recurring(rows)
        by_status = {status: 0 for status in STATUS_ORDER}
        by_device: dict[str, dict[str, Any]] = {}
        month = datetime.now().strftime("%Y-%m")
        closed_this_month = 0
        for row in rows:
            status = str(row.get("status", ""))
            if status in by_status:
                by_status[status] += 1
            if str(row.get("收口时间") or "").startswith(month):
                closed_this_month += 1
            device = str(row.get("设备编号", ""))
            slot = by_device.setdefault(device, {
                "设备编号": device,
                "设备名称": row.get("设备名称", ""),
                "故障总数": 0,
                "未闭环": 0,
                "重复故障": 0,
            })
            slot["故障总数"] += 1
            if status != STATUS_ORDER[-1]:
                slot["未闭环"] += 1
            if row.get("重复故障"):
                slot["重复故障"] += 1
        cards = [
            {"label": "待受理", "value": by_status["待受理"]},
            {"label": "流转中", "value": by_status["已受理"] + by_status["处理中"] + by_status["待复核"]},
            {"label": "本月已收口", "value": closed_this_month},
            {"label": "重复故障(30天)", "value": sum(1 for row in rows if row.get("重复故障"))},
        ]
        return {
            "cards": cards,
            "by_status": [{"status": status, "count": by_status[status]} for status in STATUS_ORDER],
            "by_device": sorted(by_device.values(), key=lambda item: item["故障总数"], reverse=True),
            "recurring": self.recurring_groups(),
        }

    # ---- 内部：重复故障标记与台账同步 ----
    def _recurring_keys(self) -> set[tuple[str, str]]:
        groups: dict[tuple[str, str], list[datetime]] = {}
        for row in store.rows(MODULE):
            moment = _parse_time(row.get("报送时间"))
            if moment is None:
                continue
            key = (str(row.get("设备编号", "")), str(row.get("故障类别", "")))
            groups.setdefault(key, []).append(moment)
        recurring: set[tuple[str, str]] = set()
        for key, moments in groups.items():
            moments.sort()
            for earlier, later in zip(moments, moments[1:]):
                if (later - earlier).days <= RECURRING_WINDOW_DAYS:
                    recurring.add(key)
                    break
        return recurring

    def _mark_recurring(self, rows: list[dict[str, Any]]) -> None:
        keys = self._recurring_keys()
        for row in rows:
            hit = (str(row.get("设备编号", "")), str(row.get("故障类别", ""))) in keys
            row["重复故障"] = hit
            row["abnormal"] = hit

    def _sync_ledger(self, entry: dict[str, Any]) -> bool:
        """收口后把处置结论写回设备台账；同一张单重复同步只更新不重复挂履历。"""
        for row in store.rows(LEDGER_MODULE):
            if str(row.get("设备编号", "")) != str(entry.get("设备编号", "")):
                continue
            row["最近故障单号"] = entry.get("故障单号", "")
            row["故障处置结论"] = entry.get("处置结论", "")
            row["故障闭环时间"] = entry.get("收口时间", "")
            history = row.setdefault("故障履历", [])
            record = {
                "故障单号": entry.get("故障单号", ""),
                "故障类别": entry.get("故障类别", ""),
                "处置结论": entry.get("处置结论", ""),
                "收口时间": entry.get("收口时间", ""),
            }
            for index, item in enumerate(history):
                if item.get("故障单号") == record["故障单号"]:
                    history[index] = record
                    break
            else:
                history.append(record)
            entry["台账已同步"] = True
            return True
        entry["台账已同步"] = False
        return False
