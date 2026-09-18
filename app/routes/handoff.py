from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..dependencies import _audit_log, require_admin
from ..services import handoff as handoff_service

router = APIRouter()


@router.get("/handoff/queue", dependencies=[Depends(require_admin)])
def handoff_queue_list(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """List queued handoff tickets awaiting delivery."""
    tickets = handoff_service.get_queued_tickets()
    total = len(tickets)
    return {"count": total, "tickets": tickets[offset : offset + limit]}


@router.post("/handoff/queue/replay", dependencies=[Depends(require_admin)])
def handoff_queue_replay(
    request: Request,
    ticket_id: str | None = Query(default=None),
):
    """Replay one specific queued ticket, or all queued tickets."""
    if ticket_id:
        res = handoff_service.replay_ticket(ticket_id)
        if not res.get("success"):
            if res.get("error") == "not_found":
                raise HTTPException(status_code=404, detail=f"Queued ticket not found: {ticket_id}")
            raise HTTPException(status_code=502, detail=f"Replay delivery failed for ticket {ticket_id}")
        _audit_log(request, "handoff_replay", ticket_id)
        return res

    res = handoff_service.replay_all_queued()
    _audit_log(request, "handoff_replay_all", extra=res)
    return res


@router.delete("/handoff/queue/{ticket_id}", dependencies=[Depends(require_admin)])
def handoff_queue_delete(ticket_id: str, request: Request):
    """Dismiss and remove a queued ticket."""
    if not handoff_service.dismiss_ticket(ticket_id):
        raise HTTPException(status_code=404, detail=f"Queued ticket not found: {ticket_id}")
    _audit_log(request, "handoff_delete", ticket_id)
    return {"deleted": ticket_id}
