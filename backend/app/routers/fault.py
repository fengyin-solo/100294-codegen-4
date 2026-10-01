"""故障报送接口：报修、受理、处置、复核与收口在同一条流水上完成。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.fault import FaultService

router = APIRouter(prefix="/api/fault", tags=["故障报送"])

service = FaultService()

LIST_FIELDS = [
    "故障单号", "设备编号", "设备名称", "故障名称", "故障现象", "故障级别",
    "报修人", "报修时间", "责任人", "责任班组", "受理时间", "处置时间",
    "复核时间", "处置结论", "状态",
]
STATUSES = ["待受理", "处理中", "待复核", "已关闭"]
ACTIONS = ["accept", "save_record", "submit_review", "review", "update_conclusion"]


def current_user(
    x_operator_name: str = Header(..., alias="X-Operator-Name", description="当前操作人"),
    x_operator_team: str = Header(..., alias="X-Operator-Team", description="当前操作班组"),
    x_request_key: str = Header(default="", alias="X-Request-Key", description="前端生成的幂等键，用于断线重试"),
) -> dict[str, str]:
    operator = x_operator_name.strip()
    team = x_operator_team.strip()
    if not operator or not team:
        raise HTTPException(status_code=400, detail="操作人和操作班组不能为空")
    return {"operator": operator, "team": team, "request_key": x_request_key.strip()}


@router.get("/board")
def board() -> dict[str, Any]:
    """报修看板：状态卡片、重复故障和最近明细共用一份实时口径。"""
    payload = service.board()
    payload["recurring"] = service.recurring_devices()
    return payload


@router.get("/recurring")
def recurring(
    month: str | None = Query(default=None, description="按月统计，格式 YYYY-MM；默认当月"),
) -> dict[str, Any]:
    """按设备归类一个月内重复出现的同一故障。"""
    return {"month": month or "当月", "items": service.recurring_devices(month)}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按故障单号、故障名称或现象检索"),
    status: str | None = Query(default=None, description="待受理、处理中、待复核、已关闭"),
    device_code: str | None = Query(default=None, alias="device", description="设备编号"),
    recurring: bool | None = Query(default=None, description="是否只看月内重复故障"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if status and status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"状态仅支持：{'、'.join(STATUSES)}")
    items, total = service.list_entries(
        keyword=keyword,
        status=status,
        device_code=device_code,
        recurring=recurring,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "fault", "label": "设备故障报送", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict[str, Any]:
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"故障单 {entry_id} 不存在")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload, user: dict[str, str] = Depends(current_user)) -> ActionResult:
    """提交故障报修；同设备同故障存在未闭单据时并入原单。"""
    entry, message, missing = service.create_entry(
        payload.values,
        operator=user["operator"],
        team=user["team"],
        request_key=user["request_key"],
    )
    if missing:
        return ActionResult(ok=False, message=f"{message}：{'、'.join(missing)}")
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(
    entry_id: int,
    payload: EntryPayload,
    user: dict[str, str] = Depends(current_user),
) -> ActionResult:
    """执行受理、保存处置、提交复核、复核关闭；动作只允许按流水方向推进。"""
    action = str(payload.values.get("action") or "").strip()
    if action not in ACTIONS:
        return ActionResult(ok=False, message=f"动作「{action}」不属于故障报送可执行范围")
    try:
        entry, message = service.run_action(
            entry_id,
            action,
            payload.values,
            operator=user["operator"],
            team=user["team"],
            request_key=user["request_key"],
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
