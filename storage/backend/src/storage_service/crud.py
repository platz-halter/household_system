from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from storage_service.models import Item, ItemAlias, Location
from storage_service.schemas import ItemCreate, ItemUpdate, LocationIn


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
        item.aliases = [ItemAlias(alias=a) for a in dict.fromkeys(data.aliases)]

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
    limit: int = 50,
    offset: int = 0,
) -> list[Item]:
    query = _item_query().join(Location, isouter=True).distinct()

    if q:
        pattern = f"%{q}%"
        query = query.outerjoin(ItemAlias).where(
            or_(
                Item.name.ilike(pattern),
                Item.description.ilike(pattern),
                ItemAlias.alias.ilike(pattern),
            )
        )
    if room:
        query = query.where(Location.room.ilike(room))
    if level:
        query = query.where(Location.level.ilike(level))
    if shelf:
        query = query.where(Location.shelf.ilike(shelf))
    if min_quantity is not None:
        query = query.where(Item.quantity >= min_quantity)
    if max_quantity is not None:
        query = query.where(Item.quantity <= max_quantity)

    query = query.order_by(Item.name).limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().unique().all())


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
