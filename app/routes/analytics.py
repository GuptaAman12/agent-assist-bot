from fastapi import APIRouter, Depends, Query, Request

from ..dependencies import require_admin
from ..services import analytics as analytics_service
from ..services.rag import KnowledgeBase
from ..schemas import FeedbackRequest

router = APIRouter()

@router.post("/analytics/feedback")
def submit_feedback(request: FeedbackRequest):
    """Log user feedback for an AI response."""
    analytics_service.log_feedback(
        transcript=request.transcript,
        positive=request.positive,
        assist_request_id=request.assist_request_id
    )
    return {"status": "ok"}



@router.get("/stats", dependencies=[Depends(require_admin)])
def stats(request: Request):
    """Process-local usage aggregates (reset on restart)."""
    kb: KnowledgeBase = request.app.state.knowledge_base
    return {"counters": analytics_service.snapshot(), "kb_count": kb.count}


@router.get("/analytics/summary", dependencies=[Depends(require_admin)])
def analytics_summary():
    """Aggregated usage, token consumption, and cost estimates across all services."""
    return analytics_service.get_analytics_summary()


@router.get("/kb/unmatched", dependencies=[Depends(require_admin)])
def kb_unmatched(request: Request, limit: int = Query(default=50, ge=1, le=100)):
    """Unmatched queries from the analytics log for KB curation, with in_kb status."""
    kb: KnowledgeBase = request.app.state.knowledge_base
    unmatched = analytics_service.get_unmatched_queries(limit=limit)
    existing_questions = {
        (e.get("question") or "").strip().lower()
        for e in kb.snapshot(include_deleted=False)
        if e.get("question")
    }
    for item in unmatched:
        item["in_kb"] = item["transcript"].strip().lower() in existing_questions
    return {"count": len(unmatched), "unmatched": unmatched}
