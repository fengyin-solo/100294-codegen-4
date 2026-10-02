"""设备故障报送接口：开单去重、单向流水、断点续处置、重复故障看板与台账同步。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.faultreport import FaultReportService

router = APIRouter(prefix="/api/faultreport", tags=["故障报送"])

service = FaultReportService()

LIST_FIELDS = ["故障单号", "设备编号", "设备名称", "故障类别", "故障描述", "报修人", "报送时间", "故障状态"]
STATUSES = ["待受理", "已受理", "处理中", "待复核", "已收口"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按故障单号检索"),
    status: str | None = Query(default=None, description="待受理、已受理、处理中、待复核、已收口"),
    device: str | None = Query(default=None, description="按设备编号过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按故障单号、状态与设备过滤故障工单列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, device=device, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/board")
def board() -> dict[str, Any]:
    """报修看板：状态分布、按设备归类与重复故障都从明细现算，保证与明细同步。"""
    return service.board()


@router.get("/recurring")
def recurring() -> dict[str, Any]:
    """一个月内重复冒出来的故障：按设备+故障类别归组，单独拎出来。"""
    return {"groups": service.recurring_groups()}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出故障工单清单：返回当前全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "faultreport", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单张故障工单明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"故障工单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """报送故障：同设备同故障已有未闭环工单时不再另开新单，直接返回那张单。"""
    entry, missing, outcome = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    if outcome == "duplicate" and entry is not None:
        return ActionResult(
            ok=False,
            message=f"该设备同类故障已有未闭环工单 {entry.get('故障单号')}，不再另开新单，请接着那张单处置",
            entry=entry,
        )
    return ActionResult(ok=True, message="故障报送单已登记，等待受理", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """执行受理、开始处理、提交复核、复核收口；回退与跳步都会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    operator = str(payload.values.get("operator") or "").strip()
    entry, message = service.run_action(entry_id, action, operator)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/steps", response_model=ActionResult)
def save_step(entry_id: int, payload: EntryPayload) -> ActionResult:
    """保存受理/处理/复核处置记录：断线后从断掉的那步接着填，已填写的不允许覆盖。"""
    step = str(payload.values.get("step") or "").strip()
    content = str(payload.values.get("content") or "").strip()
    operator = str(payload.values.get("operator") or "").strip()
    entry, message = service.save_step(entry_id, step, content, operator)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/conclusion", response_model=ActionResult)
def save_conclusion(entry_id: int, payload: EntryPayload) -> ActionResult:
    """填写处置结论：只有本设备责任人能改，别的班组提交会被拦下。"""
    operator = str(payload.values.get("operator") or "").strip()
    conclusion = str(payload.values.get("conclusion") or "").strip()
    entry, message = service.save_conclusion(entry_id, operator, conclusion)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
