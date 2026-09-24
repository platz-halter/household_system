from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from storage_service.models import Item, ItemAlias, Location
from storage_service.schemas import ItemCreate, ItemUpdate, LocationIn

SORTABLE_COLUMNS = {
    "name": Item.name,
    "quantity": Item.quantity,
    "created_at": Item.created_at,
    "updated_at": Item.updated_at,
}


async def get_or_create_location(db: AsyncSession, loc: LocationIn) -> Location:
    result = await db.execute(
        select(Location).where(
            Location.room == loc.room,
            Location.level == loc.level,
            Location.shelf == loc.shelf,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing
    new_loc = Location(room=loc.room, level=loc.level, shelf=loc.shelf)
    db.add(new_loc)
    await db.flush()  # get its id without committing yet
    return new_loc


def _item_query():
    return select(Item).options(selectinload(Item.aliases), selectinload(Item.location))


async def get_item(db: AsyncSession, item_id: int) -> Item | None:
    result = await db.execute(_item_query().where(Item.id == item_id))
    return result.scalar_one_or_none()


async def create_item(db: AsyncSession, data: ItemCreate) -> Item:
    location = (
        await get_or_create_location(db, data.location) if data.location else None
    )

    item = Item(
        name=data.name,
        description=data.description,
        quantity_type=data.quantity_type,
        quantity=data.quantity,
        quantity_note=data.quantity_note,
        location=location,
        aliases=[
            ItemAlias(alias=a) for a in dict.fromkeys(data.aliases)
        ],  # dedupe, keep order
    )
    db.add(item)
    await db.commit()
    await db.refresh(
        item, attribute_names=["aliases", "location", "updated_at", "created_at"]
    )
    return item


async def update_item(db: AsyncSession, item: Item, data: ItemUpdate) -> Item:
    if data.name is not None:
        item.name = data.name
    if data.description is not None:
        item.description = data.description
    if data.quantity_type is not None:
        item.quantity_type = data.quantity_type
    if data.quantity is not None:
        item.quantity = data.quantity
    if data.quantity_note is not None:
        item.quantity_note = data.quantity_note
    if data.location is not None:
        item.location = await get_or_create_location(db, data.location)
    if data.aliases is not None:
        desired = list(dict.fromkeys(data.aliases))  # dedupe, preserve order
        desired_set = set(desired)
        existing_by_text = {a.alias: a for a in item.aliases}

        # Remove aliases no longer wanted.
        for alias_text, alias_obj in list(existing_by_text.items()):
            if alias_text not in desired_set:
                item.aliases.remove(alias_obj)

        # Add only genuinely new aliases — leaving unchanged ones alone
        # avoids a DELETE+INSERT pair for the same (item_id, alias) row,
        # which previously tripped the unique constraint because the
        # INSERT could flush before the matching DELETE.
        for alias_text in desired:
            if alias_text not in existing_by_text:
                item.aliases.append(ItemAlias(alias=alias_text))

    await db.commit()
    await db.refresh(
        item, attribute_names=["aliases", "location", "updated_at", "created_at"]
    )
    return item


async def search_items(
    db: AsyncSession,
    *,
    q: str | None = None,
    room: str | None = None,
    level: str | None = None,
    shelf: str | None = None,
    min_quantity: int | None = None,
    max_quantity: int | None = None,
    sort_by: str = "name",
    sort_dir: str = "asc",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Item], int]:
    """Returns (page_of_items, total_matching_count) so the frontend can
    render real page numbers rather than guessing from page length."""

    def _apply_filters(stmt):
        if q:
            pattern = f"%{q}%"
            stmt = stmt.outerjoin(ItemAlias).where(
                or_(
                    Item.name.ilike(pattern),
                    Item.description.ilike(pattern),
                    ItemAlias.alias.ilike(pattern),
                )
            )
        if room:
            stmt = stmt.where(Location.room.ilike(room))
        if level:
            stmt = stmt.where(Location.level.ilike(level))
        if shelf:
            stmt = stmt.where(Location.shelf.ilike(shelf))
        if min_quantity is not None:
            stmt = stmt.where(Item.quantity >= min_quantity)
        if max_quantity is not None:
            stmt = stmt.where(Item.quantity <= max_quantity)
        return stmt

    base = select(Item.id).select_from(Item).join(Location, isouter=True)
    count_stmt = _apply_filters(base)
    total = await db.scalar(
        select(func.count()).select_from(count_stmt.distinct().subquery())
    )

    sort_col = SORTABLE_COLUMNS.get(sort_by, Item.name)
    order = sort_col.desc() if sort_dir == "desc" else sort_col.asc()

    query = _apply_filters(_item_query().join(Location, isouter=True).distinct())
    query = query.order_by(order, Item.id).limit(limit).offset(offset)
    result = await db.execute(query)
    items = list(result.scalars().unique().all())

    return items, total or 0


async def list_locations(db: AsyncSession) -> list[Location]:
    result = await db.execute(
        select(Location).order_by(Location.room, Location.level, Location.shelf)
    )
    return list(result.scalars().all())


async def bulk_delete_items(
    db: AsyncSession, item_ids: list[int]
) -> tuple[int, list[int]]:
    result = await db.execute(select(Item.id).where(Item.id.in_(item_ids)))
    found_ids = set(result.scalars().all())
    not_found = [i for i in item_ids if i not in found_ids]

    if found_ids:
        await db.execute(delete(Item).where(Item.id.in_(found_ids)))
        await db.commit()

    return len(found_ids), not_found
