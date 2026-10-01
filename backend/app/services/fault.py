"""故障报送业务规则。

故障单只允许沿「待受理 → 处理中 → 待复核 → 已关闭」向前推进；复核不通过时
仅允许回到处理中补齐处置。处置记录按步骤追加，断线重试用同一 request_key
命中已完成动作，避免把已经填写的内容顶掉。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "fault"
REGISTER_MODULE = "register"

STATUS_PENDING = "待受理"
STATUS_PROCESSING = "处理中"
STATUS_REVIEWING = "待复核"
STATUS_CLOSED = "已关闭"
OPEN_STATUSES = {STATUS_PENDING, STATUS_PROCESSING, STATUS_REVIEWING}

REQUIRED_CREATE_FIELDS = ["设备编号", "故障名称", "故障现象"]

ACTIONS = {
    "accept": "受理",
    "save_record": "保存处置记录",
    "submit_review": "提交复核",
    "review": "复核",
    "update_conclusion": "修改处置结论",
}
STEP_LABELS = {
    "create": "提交报修",
    "accept": "受理",
    "save": "保存处置记录",
    "submit": "提交复核",
    "review_pass": "复核通过并关闭",
    "review_back": "复核退回补充处置",
    "conclusion": "修改处置结论",
}


class FaultService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        device_code: str | None = None,
        recurring: bool | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._sorted_rows()
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("故障单号", ""))
                or keyword in str(row.get("故障名称", ""))
                or keyword in str(row.get("故障现象", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if device_code:
            rows = [row for row in rows if row.get("设备编号") == device_code]
        rows = [self._with_recurrence(row) for row in rows]
        if recurring is not None:
            rows = [row for row in rows if bool(row.get("月内重复")) == recurring]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._with_recurrence(entry) if entry else None

    def create_entry(
        self,
        values: dict[str, Any],
        *,
        operator: str,
        team: str,
        request_key: str,
    ) -> tuple[dict[str, Any] | None, str, list[str]]:
        missing = [field for field in REQUIRED_CREATE_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, "缺少必填字段", missing

        device_code = str(values.get("设备编号") or "").strip()
        fault_name = str(values.get("故障名称") or "").strip()
        device = self._find_device(device_code)
        if device is None:
            return None, f"设备台账中不存在设备 {device_code}，请先完成设备登记", []

        owner_team = str(device.get("责任班组") or "").strip()
        owner = str(device.get("责任人") or "").strip()
        if not owner_team or not owner:
            return None, f"设备 {device_code} 未配置责任班组或责任人，暂不能派单", []

        existing = self._open_ticket(device_code, fault_name)
        now = self._now()
        if existing is not None:
            if self._same_request(existing, "create", request_key):
                return existing, "已恢复到这张未关闭故障单，未重复开单", []
            existing.setdefault("重复报修", []).append({
                "报修人": operator,
                "班组": team,
                "时间": now,
                "说明": str(values.get("故障现象") or "").strip(),
            })
            existing["故障现象"] = self._append_text(str(existing.get("故障现象") or ""), str(values.get("故障现象") or "").strip())
            self._add_log(existing, "create", operator, team, now, "重复报修并入未关闭单据")
            self._remember_request(existing, "create", request_key)
            device["运行状态"] = f"故障处理中（{existing['故障单号']}）"
            return self._with_recurrence(existing), "同一设备同一故障已有未关闭单据，已并入原单，不另开新单", []

        rows = store.rows(MODULE)
        entry_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        entry: dict[str, Any] = {
            "id": entry_id,
            "故障单号": f"FAULT-{entry_id:04d}",
            "status": STATUS_PENDING,
            "current_step": "pending",
            "pending": True,
            "abnormal": False,
            "设备编号": device_code,
            "设备名称": str(values.get("设备名称") or device.get("设备名称") or "").strip(),
            "故障名称": fault_name,
            "故障现象": str(values.get("故障现象") or "").strip(),
            "故障级别": str(values.get("故障级别") or "一般").strip(),
            "报修人": operator,
            "报修班组": team,
            "报修时间": now,
            "责任班组": owner_team,
            "责任人": owner,
            "受理人": "",
            "受理时间": "",
            "处置记录": "",
            "处置人": "",
            "处置时间": "",
            "复核人": "",
            "复核意见": "",
            "复核时间": "",
            "处置结论": "",
            "关闭时间": "",
            "重复报修": [],
            "操作日志": [],
            "request_keys": {},
        }
        self._add_log(entry, "create", operator, team, now)
        self._remember_request(entry, "create", request_key)
        rows.append(entry)
        device["运行状态"] = f"待受理（{entry['故障单号']}）"
        return self._with_recurrence(entry), "故障报送单已提交，等待责任班组受理", []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any],
        *,
        operator: str,
        team: str,
        request_key: str,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"故障单 {entry_id} 不存在"
        if action not in ACTIONS:
            return None, f"动作「{action}」不属于故障报送可执行范围"

        restored = self._same_request(entry, action, request_key)
        if restored is not None:
            return entry, "已从断线步骤恢复，重复请求未覆盖原记录"

        handler = getattr(self, f"_action_{action}")
        result, message = handler(entry, values, operator=operator, team=team, request_key=request_key)
        return (self._with_recurrence(result) if result else None), message

    def board(self) -> dict[str, Any]:
        rows = store.rows(MODULE)
        status_counts = {status: 0 for status in (STATUS_PENDING, STATUS_PROCESSING, STATUS_REVIEWING, STATUS_CLOSED)}
        for row in rows:
            status_counts[str(row.get("status"))] = status_counts.get(str(row.get("status")), 0) + 1
        recurring = self.recurring_devices()
        cards = [
            {"label": "待受理", "value": status_counts[STATUS_PENDING]},
            {"label": "处理中", "value": status_counts[STATUS_PROCESSING]},
            {"label": "待复核", "value": status_counts[STATUS_REVIEWING]},
            {"label": "月内重复故障", "value": len(recurring)},
        ]
        return {"cards": cards, "status_counts": status_counts, "items": [self._with_recurrence(dict(row)) for row in self._sorted_rows()[:10]]}

    def recurring_devices(self, month: str | None = None) -> list[dict[str, Any]]:
        cutoff = self._month_cutoff(month)
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in store.rows(MODULE):
            event_at = self._parse_time(str(row.get("关闭时间") or row.get("报修时间") or ""))
            if event_at is not None and event_at < cutoff:
                continue
            key = (str(row.get("设备编号") or ""), str(row.get("故障名称") or ""))
            groups.setdefault(key, []).append(row)

        result = []
        for (device_code, fault_name), tickets in groups.items():
            if len(tickets) < 2:
                continue
            tickets = sorted(tickets, key=lambda item: int(item.get("id", 0)))
            latest = tickets[-1]
            result.append({
                "设备编号": device_code,
                "设备名称": latest.get("设备名称", ""),
                "故障名称": fault_name,
                "责任班组": latest.get("责任班组", ""),
                "责任人": latest.get("责任人", ""),
                "月内次数": len(tickets),
                "最近单号": latest.get("故障单号", ""),
                "最近状态": latest.get("status", ""),
                "最近时间": latest.get("关闭时间") or latest.get("报修时间", ""),
                "最近处置结论": latest.get("处置结论", ""),
                "故障单号": [item.get("故障单号") for item in tickets],
            })
        return sorted(result, key=lambda item: (-int(item["月内次数"]), str(item["最近时间"])), reverse=False)

    def _action_accept(
        self,
        entry: dict[str, Any],
        values: dict[str, Any],
        *,
        operator: str,
        team: str,
        request_key: str,
    ) -> tuple[dict[str, Any] | None, str]:
        self._assert_owner(entry, operator, team)
        if entry["status"] != STATUS_PENDING:
            return None, f"当前状态为{entry['status']}，受理后的故障单不能回到待受理"
        now = self._now()
        entry["status"] = STATUS_PROCESSING
        entry["current_step"] = "processing"
        entry["pending"] = True
        entry["受理人"] = operator
        entry["受理时间"] = now
        self._add_log(entry, "accept", operator, team, now)
        self._remember_request(entry, "accept", request_key)
        self._update_device(entry, f"故障处理中（{entry['故障单号']}）", str(entry.get("处置结论") or ""), now)
        return entry, "故障单已受理，请继续填写处置记录"

    def _action_save_record(
        self,
        entry: dict[str, Any],
        values: dict[str, Any],
        *,
        operator: str,
        team: str,
        request_key: str,
    ) -> tuple[dict[str, Any] | None, str]:
        self._assert_owner(entry, operator, team)
        if entry["status"] not in {STATUS_PROCESSING}:
            return None, f"当前状态为{entry['status']}，只有处理中的故障单能补充处置记录"
        record = str(values.get("处置记录") or "").strip()
        handler = str(values.get("处置人") or operator).strip()
        if not record:
            return None, "处置记录不能为空"
        now = str(values.get("处置时间") or "").strip() or self._now()
        # 处置记录按追加保存：重试或继续补充都不会覆盖上一位处置人已经填好的内容。
        entry["处置记录"] = self._append_text(str(entry.get("处置记录") or ""), f"{handler} {now}：{record}")
        entry["处置人"] = self._append_text(str(entry.get("处置人") or ""), handler)
        entry["处置时间"] = now
        entry["current_step"] = "processing"
        self._add_log(entry, "save", operator, team, now)
        self._remember_request(entry, "save_record", request_key)
        self._update_device(entry, f"故障处理中（{entry['故障单号']}）", "处置记录已保存，待提交复核", now)
        return entry, "处置记录已保存，可从当前处理步骤继续提交复核"

    def _action_submit_review(
        self,
        entry: dict[str, Any],
        values: dict[str, Any],
        *,
        operator: str,
        team: str,
        request_key: str,
    ) -> tuple[dict[str, Any] | None, str]:
        self._assert_owner(entry, operator, team)
        if entry["status"] != STATUS_PROCESSING:
            return None, f"当前状态为{entry['status']}，不能提交复核"
        if not str(entry.get("处置记录") or "").strip():
            return None, "尚未填写处置记录，不能提交复核"
        now = self._now()
        entry["status"] = STATUS_REVIEWING
        entry["current_step"] = "reviewing"
        self._add_log(entry, "submit", operator, team, now)
        self._remember_request(entry, "submit_review", request_key)
        self._update_device(entry, f"待复核（{entry['故障单号']}）", str(entry.get("处置结论") or ""), now)
        return entry, "已提交复核，复核通过后才允许关闭"

    def _action_review(
        self,
        entry: dict[str, Any],
        values: dict[str, Any],
        *,
        operator: str,
        team: str,
        request_key: str,
    ) -> tuple[dict[str, Any] | None, str]:
        self._assert_owner(entry, operator, team)
        if entry["status"] != STATUS_REVIEWING:
            return None, f"当前状态为{entry['status']}，处理中未经复核不许收口"
        passed = values.get("passed")
        passed = str(passed).strip().lower() in {"true", "1", "yes", "通过"} if passed is not None else True
        opinion = str(values.get("复核意见") or "").strip()
        conclusion = str(values.get("处置结论") or "").strip()
        if passed and not conclusion:
            return None, "复核通过并关闭时必须填写处置结论"

        now = self._now()
        entry["复核人"] = operator
        entry["复核意见"] = opinion
        entry["复核时间"] = now

        if not passed:
            entry["status"] = STATUS_PROCESSING
            entry["current_step"] = "processing"
            entry["pending"] = True
            self._add_log(entry, "review_back", operator, team, now, opinion or "复核不通过，退回补充处置")
            self._remember_request(entry, "review", request_key)
            self._update_device(entry, f"退回补充处置（{entry['故障单号']}）", "复核不通过，需补充处置", now)
            return entry, "复核未通过，已退回处理中，原处置记录仍保留"

        entry["处置结论"] = conclusion
        entry["status"] = STATUS_CLOSED
        entry["current_step"] = "done"
        entry["pending"] = False
        entry["abnormal"] = self._recurring_count(entry) >= 2
        entry["关闭时间"] = now
        self._add_log(entry, "review_pass", operator, team, now, opinion)
        self._remember_request(entry, "review", request_key)
        self._sync_ledger(entry, now)
        return entry, "复核通过，故障单已关闭并同步设备台账"

    def _action_update_conclusion(
        self,
        entry: dict[str, Any],
        values: dict[str, Any],
        *,
        operator: str,
        team: str,
        request_key: str,
    ) -> tuple[dict[str, Any] | None, str]:
        self._assert_owner(entry, operator, team, require_person=True)
        if entry["status"] != STATUS_CLOSED:
            return None, "只有关闭后的故障单允许修改处置结论"
        conclusion = str(values.get("处置结论") or "").strip()
        if not conclusion:
            return None, "处置结论不能为空"
        now = self._now()
        old_conclusion = entry.get("处置结论", "")
        entry["处置结论"] = conclusion
        self._add_log(entry, "conclusion", operator, team, now, f"{old_conclusion} → {conclusion}")
        self._remember_request(entry, "update_conclusion", request_key)
        self._sync_ledger(entry, now)
        return entry, "处置结论已更新，并同步到设备台账"

    def _assert_owner(
        self,
        entry: dict[str, Any],
        operator: str,
        team: str,
        *,
        require_person: bool = False,
    ) -> None:
        if team != str(entry.get("责任班组") or ""):
            raise PermissionError("非本设备责任班组只能查看，不能执行该操作")
        if require_person and operator != str(entry.get("责任人") or ""):
            raise PermissionError("收口后的处置结论只有本设备责任人能改")

    def _open_ticket(self, device_code: str, fault_name: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if (
                row.get("设备编号") == device_code
                and row.get("故障名称") == fault_name
                and row.get("status") in OPEN_STATUSES
            ):
                return row
        return None

    def _find_device(self, device_code: str) -> dict[str, Any] | None:
        for row in store.rows(REGISTER_MODULE):
            if row.get("设备编号") == device_code:
                return row
        return None

    def _sync_ledger(self, entry: dict[str, Any], at: str) -> None:
        device = self._find_device(str(entry.get("设备编号") or ""))
        if device is None:
            return
        device["运行状态"] = "正常运行"
        device["最近故障单号"] = entry.get("故障单号", "")
        device["最近故障结论"] = entry.get("处置结论", "")
        device["最近故障时间"] = at
        device["status"] = "正常运行"
        device["pending"] = False
        device["abnormal"] = bool(entry.get("abnormal"))

    def _update_device(self, entry: dict[str, Any], running_status: str, conclusion: str, at: str) -> None:
        device = self._find_device(str(entry.get("设备编号") or ""))
        if device is None:
            return
        device["运行状态"] = running_status
        device["最近故障单号"] = entry.get("故障单号", "")
        device["最近故障结论"] = conclusion
        device["最近故障时间"] = at
        device["status"] = "故障处理中"
        device["pending"] = True
        device["abnormal"] = True

    def _recurring_count(self, entry: dict[str, Any], month: str | None = None) -> int:
        cutoff = self._month_cutoff(month)
        count = 0
        for row in store.rows(MODULE):
            if row.get("设备编号") != entry.get("设备编号") or row.get("故障名称") != entry.get("故障名称"):
                continue
            event_at = self._parse_time(str(row.get("关闭时间") or row.get("报修时间") or ""))
            if event_at is not None and event_at >= cutoff:
                count += 1
        return count

    def _with_recurrence(self, entry: dict[str, Any]) -> dict[str, Any]:
        count = self._recurring_count(entry)
        entry["月内重复次数"] = count
        entry["月内重复"] = count >= 2
        return entry

    def _same_request(self, entry: dict[str, Any], action: str, request_key: str) -> dict[str, Any] | None:
        if not request_key:
            return None
        if entry.get("request_keys", {}).get(action) == request_key:
            return entry
        return None

    def _remember_request(self, entry: dict[str, Any], action: str, request_key: str) -> None:
        if request_key:
            entry.setdefault("request_keys", {})[action] = request_key

    def _add_log(
        self,
        entry: dict[str, Any],
        step: str,
        operator: str,
        team: str,
        at: str,
        note: str = "",
    ) -> None:
        entry.setdefault("操作日志", []).append({
            "step": step,
            "action": STEP_LABELS.get(step, step),
            "operator": operator,
            "team": team,
            "at": at,
            "note": note,
        })

    def _sorted_rows(self, rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        return sorted(rows or store.rows(MODULE), key=lambda row: int(row.get("id", 0)), reverse=True)

    def _month_cutoff(self, month: str | None) -> datetime:
        if month:
            return datetime.strptime(f"{month}-01 00:00", "%Y-%m-%d %H:%M")
        first_day = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return first_day

    def _parse_time(self, value: str) -> datetime | None:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        return None

    def _append_text(self, original: str, addition: str) -> str:
        addition = addition.strip()
        if not addition:
            return original
        if not original:
            return addition
        if addition in original:
            return original
        return f"{original}\n{addition}"

    def _now(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M")


fault_service = FaultService()
