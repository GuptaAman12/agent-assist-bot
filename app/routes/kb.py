import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from ..dependencies import _audit_log, require_admin
from ..schemas import KBEntryRequest
from ..services.rag import KnowledgeBase

router = APIRouter()


@router.get("/kb", dependencies=[Depends(require_admin)])
def kb_list(
    request: Request,
    limit: int | None = Query(default=None, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    include_deleted: bool = False,
):
    kb: KnowledgeBase = request.app.state.knowledge_base
    entries = kb.snapshot(include_deleted=include_deleted)
    total = len(entries)
    if limit is not None:
        entries = entries[offset : offset + limit]
    return {"count": total, "entries": entries, "limit": limit, "offset": offset}


@router.post("/kb", dependencies=[Depends(require_admin)])
def kb_add(entry: KBEntryRequest, request: Request):
    kb: KnowledgeBase = request.app.state.knowledge_base
    try:
        created = kb.add_entry(entry.question, entry.response)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _audit_log(request, "kb_add", created["id"], {"question": entry.question})
    return created


@router.put("/kb/{entry_id}", dependencies=[Depends(require_admin)])
def kb_update(entry_id: str, entry: KBEntryRequest, request: Request):
    kb: KnowledgeBase = request.app.state.knowledge_base
    try:
        updated = kb.update_entry(entry_id, entry.question, entry.response)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Unknown entry id: {entry_id}")
    _audit_log(request, "kb_update", entry_id)
    return updated


@router.delete("/kb/{entry_id}", dependencies=[Depends(require_admin)])
def kb_delete(entry_id: str, request: Request):
    kb: KnowledgeBase = request.app.state.knowledge_base
    if not kb.remove_entry(entry_id):
        raise HTTPException(status_code=404, detail=f"Unknown entry id: {entry_id}")
    _audit_log(request, "kb_delete", entry_id)
    return {"deleted": entry_id, "count": kb.count, "undo_token": entry_id}


@router.post("/kb/{entry_id}/restore", dependencies=[Depends(require_admin)])
def kb_restore(entry_id: str, request: Request):
    kb: KnowledgeBase = request.app.state.knowledge_base
    restored = kb.restore_entry(entry_id)
    if restored is None:
        raise HTTPException(status_code=404, detail=f"Unknown or not-deleted entry id: {entry_id}")
    _audit_log(request, "kb_restore", entry_id)
    return restored


@router.post("/kb/reload", dependencies=[Depends(require_admin)])
def kb_reload(request: Request):
    kb: KnowledgeBase = request.app.state.knowledge_base
    kb.reload()
    _audit_log(request, "kb_reload")
    return {"reloaded": True, "count": kb.count}


@router.get("/kb/export", dependencies=[Depends(require_admin)])
def kb_export(request: Request):
    kb: KnowledgeBase = request.app.state.knowledge_base
    entries = kb.snapshot(include_deleted=False)
    _audit_log(request, "kb_export", extra={"count": len(entries)})
    return JSONResponse(
        content=entries,
        headers={"Content-Disposition": 'attachment; filename="knowledge_base.json"'},
    )


@router.post("/kb/import", dependencies=[Depends(require_admin)])
async def kb_import(request: Request):
    content_type = request.headers.get("content-type", "")
    entries_data = None
    if "multipart/form-data" in content_type:
        form = await request.form()
        file = form.get("file")
        if not file:
            raise HTTPException(status_code=400, detail="Missing file field 'file'")
        content = await file.read()
        try:
            data = json.loads(content.decode("utf-8"))
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid JSON file")
        entries_data = data["entries"] if isinstance(data, dict) and "entries" in data else data
    else:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid JSON body")
        entries_data = body["entries"] if isinstance(body, dict) and "entries" in body else body

    if not isinstance(entries_data, list):
        raise HTTPException(status_code=422, detail="Import payload must be a JSON array")

    kb: KnowledgeBase = request.app.state.knowledge_base
    try:
        count = kb.import_entries(entries_data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _audit_log(request, "kb_import", extra={"count": count})
    return {"imported": count, "count": kb.count}
