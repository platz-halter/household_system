import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import CurrentUser, require_role
from shared.db import Base, engine, get_db
from storage_service import crud
from storage_service.schemas import (
    BulkDeleteRequest,
    BulkDeleteResult,
    ItemCreate,
    ItemOut,
    ItemUpdate,
)

IMAGE_DIR = Path("/app/data/images")
IMAGE_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = (
    8 * 1024 * 1024
)  # 8 MB — plenty for item photos, keeps the volume sane


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dev convenience only — replace with Alembic migrations before this
    # sees anything resembling production data.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="Household System — Storage (cellar/item tracking)", lifespan=lifespan
)

# Any authenticated user can read; only admin/user (not viewer) can write.
can_read = require_role("admin", "user", "viewer")
can_write = require_role("admin", "user")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/items", response_model=list[ItemOut])
async def list_items(
    q: str | None = Query(
        default=None, description="Free-text search: name, description, aliases"
    ),
    room: str | None = None,
    level: str | None = None,
    shelf: str | None = None,
    min_quantity: int | None = Query(default=None, ge=0),
    max_quantity: int | None = Query(default=None, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_read),
):
    items = await crud.search_items(
        db,
        q=q,
        room=room,
        level=level,
        shelf=shelf,
        min_quantity=min_quantity,
        max_quantity=max_quantity,
        limit=limit,
        offset=offset,
    )
    return [ItemOut.from_model(i) for i in items]


@app.post("/items", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
async def create_item(
    data: ItemCreate,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_write),
):
    item = await crud.create_item(db, data)
    return ItemOut.from_model(item)


@app.get("/items/{item_id}", response_model=ItemOut)
async def get_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_read),
):
    item = await crud.get_item(db, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not found"
        )
    return ItemOut.from_model(item)


@app.patch("/items/{item_id}", response_model=ItemOut)
async def patch_item(
    item_id: int,
    data: ItemUpdate,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_write),
):
    item = await crud.get_item(db, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not found"
        )
    item = await crud.update_item(db, item, data)
    return ItemOut.from_model(item)


@app.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_write),
):
    deleted, _ = await crud.bulk_delete_items(db, [item_id])
    if deleted == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not found"
        )


@app.post("/items/bulk-delete", response_model=BulkDeleteResult)
async def bulk_delete(
    body: BulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_write),
):
    deleted, not_found = await crud.bulk_delete_items(db, body.item_ids)
    return BulkDeleteResult(deleted=deleted, not_found=not_found)


@app.post("/items/{item_id}/image", response_model=ItemOut)
async def upload_item_image(
    item_id: int,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_write),
):
    item = await crud.get_item(db, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not found"
        )

    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported image type '{file.content_type}'. Allowed: {sorted(ALLOWED_IMAGE_TYPES)}",
        )

    contents = await file.read()
    if len(contents) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Image exceeds {MAX_IMAGE_BYTES // (1024 * 1024)}MB limit",
        )

    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[
        file.content_type
    ]
    filename = f"{item_id}-{uuid.uuid4().hex}.{ext}"
    (IMAGE_DIR / filename).write_bytes(contents)

    item.image_path = filename
    db.add(item)
    await db.commit()
    await db.refresh(
        item, attribute_names=["aliases", "location", "updated_at", "created_at"]
    )
    return ItemOut.from_model(item)


@app.get("/items/{item_id}/image")
async def get_item_image(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_read),
):
    item = await crud.get_item(db, item_id)
    if item is None or not item.image_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No image for this item"
        )

    path = IMAGE_DIR / item.image_path
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image file missing on disk"
        )
    return FileResponse(path)
