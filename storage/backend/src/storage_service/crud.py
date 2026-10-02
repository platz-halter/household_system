from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from storage_service.models import Item, ItemAlias, Location, Room
from storage_service.schemas import ItemCreate, ItemUpdate, LocationIn, RoomIn

SORTABLE_COLUMNS = {
    "name": Item.name,
    "quantity": Item.quantity,
    "created_at": Item.created_at,
    "updated_at": Item.updated_at,
}


# ---- Rooms --------------------------------------------------------------


async def list_rooms(db: AsyncSession) -> list[Room]:
    result = await db.execute(select(Room).order_by(Room.name))
    return list(result.scalars().all())


async def get_room(db: AsyncSession, room_id: int) -> Room | None:
    return await db.get(Room, room_id)


async def get_room_by_name(db: AsyncSession, name: str) -> Room | None:
    result = await db.execute(select(Room).where(Room.name == name))
    return result.scalar_one_or_none()


async def create_room(db: AsyncSession, data: RoomIn) -> Room:
    room = Room(name=data.name)
    db.add(room)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError(f"Room '{data.name}' already exists") from exc
    await db.refresh(room)
    return room


async def delete_room(db: AsyncSession, room: Room) -> None:
    """Blocks deletion only while an item actually sits in this room —
    not while a now-unused Location row still points at it (location rows
    are a shared lookup table and aren't cleaned up when an item moves
    off one, the same way they weren't before rooms existed). Once no
    item uses it, those leftover rows are deleted here too: Location.room_id
    is NOT NULL, so they'd otherwise block the room delete on a dangling
    foreign key even though nothing visible to the user still needs them."""
    items_in_use = await db.scalar(
        select(func.count())
        .select_from(Item)
        .join(Location, Item.location_id == Location.id)
        .where(Location.room_id == room.id)
    )
    if items_in_use:
        raise ValueError(
            f"'{room.name}' is still used by {items_in_use} "
            f"item{'s' if items_in_use != 1 else ''} — move or delete those items first"
        )
    await db.execute(delete(Location).where(Location.room_id == room.id))
    await db.delete(room)
    await db.commit()


# ---- Locations ------------------------------------------------------------


async def resolve_location(db: AsyncSession, loc: LocationIn) -> Location:
    """Looks up (or creates) the Location row for an existing room + level +
    shelf. Unlike the old get_or_create_location, the room itself must
    already exist (see Room above) — raises ValueError otherwise, which
    main.py turns into a 400."""
    room = await get_room_by_name(db, loc.room)
    if room is None:
        raise ValueError(f"Unknown room '{loc.room}' — add it on the Rooms page first")

    result = await db.execute(
        select(Location).where(
            Location.room_id == room.id,
            Location.level == loc.level,
            Location.shelf == loc.shelf,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing
    new_loc = Location(room_id=room.id, level=loc.level, shelf=loc.shelf)
    db.add(new_loc)
    await db.flush()  # get its id without committing yet
    return new_loc


def _item_query():
    return select(Item).options(
        selectinload(Item.aliases),
        selectinload(Item.location).selectinload(Location.room),
    )


async def reload_item(db: AsyncSession, item: Item) -> None:
    """Refreshes an item plus the nested relationships ItemOut.from_model
    needs. db.refresh(item, attribute_names=[...]) only reloads attributes
    named on `item` itself — it doesn't cascade into item.location.room,
    which would otherwise lazy-load the first time something reads
    location.room.name, crashing with MissingGreenlet (lazy loads aren't
    valid in an async context without a sync-compat shim)."""
    await db.refresh(
        item, attribute_names=["aliases", "location", "updated_at", "created_at"]
    )
    if item.location is not None:
        await db.refresh(item.location, attribute_names=["room"])


async def get_item(db: AsyncSession, item_id: int) -> Item | None:
    result = await db.execute(_item_query().where(Item.id == item_id))
    return result.scalar_one_or_none()


async def create_item(db: AsyncSession, data: ItemCreate) -> Item:
    location = await resolve_location(db, data.location) if data.location else None

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
    await reload_item(db, item)
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
        item.location = await resolve_location(db, data.location)
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
    await reload_item(db, item)
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
            stmt = stmt.where(Room.name.ilike(room))
        if level:
            stmt = stmt.where(Location.level.ilike(level))
        if shelf:
            stmt = stmt.where(Location.shelf.ilike(shelf))
        if min_quantity is not None:
            stmt = stmt.where(Item.quantity >= min_quantity)
        if max_quantity is not None:
            stmt = stmt.where(Item.quantity <= max_quantity)
        return stmt

    def _join_location(stmt):
        return stmt.join(Location, isouter=True).join(
            Room, Location.room_id == Room.id, isouter=True
        )

    base = _join_location(select(Item.id).select_from(Item))
    count_stmt = _apply_filters(base)
    total = await db.scalar(
        select(func.count()).select_from(count_stmt.distinct().subquery())
    )

    sort_col = SORTABLE_COLUMNS.get(sort_by, Item.name)
    order = sort_col.desc() if sort_dir == "desc" else sort_col.asc()

    query = _apply_filters(_join_location(_item_query()).distinct())
    query = query.order_by(order, Item.id).limit(limit).offset(offset)
    result = await db.execute(query)
    items = list(result.scalars().unique().all())

    return items, total or 0


async def list_locations(db: AsyncSession) -> list[Location]:
    result = await db.execute(
        select(Location)
        .options(selectinload(Location.room))
        .join(Room, Location.room_id == Room.id)
        .order_by(Room.name, Location.level, Location.shelf)
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


async def bulk_update_items(
    db: AsyncSession,
    item_ids: list[int],
    *,
    location: LocationIn | None,
    quantity_type,
    quantity: int | None,
    quantity_note: str | None,
) -> tuple[int, list[int]]:
    """Apply the same location and/or quantity change to a batch of
    items in one commit. Caller (main.py) only passes location/quantity_*
    through when the request actually opted into changing that field."""
    result = await db.execute(select(Item).where(Item.id.in_(item_ids)))
    found_items = list(result.scalars().all())
    found_ids = {i.id for i in found_items}
    not_found = [i for i in item_ids if i not in found_ids]

    if found_items:
        resolved_location = (
            await resolve_location(db, location) if location is not None else None
        )
        for item in found_items:
            if location is not None:
                item.location = resolved_location
            if quantity_type is not None:
                item.quantity_type = quantity_type
                item.quantity = quantity
                item.quantity_note = quantity_note
        await db.commit()

    return len(found_items), not_found
