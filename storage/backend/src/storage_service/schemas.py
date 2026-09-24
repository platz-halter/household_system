from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from storage_service.models import QuantityType


class LocationIn(BaseModel):
    room: str = Field(min_length=1, max_length=64)
    level: str | None = None
    shelf: str | None = None


class LocationOut(LocationIn):
    id: int
    model_config = {"from_attributes": True}


class ItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    aliases: list[str] = Field(default_factory=list)

    quantity_type: QuantityType = QuantityType.countable
    quantity: int | None = Field(default=None, ge=0)
    quantity_note: str | None = Field(default=None, max_length=120)

    location: LocationIn | None = None

    @model_validator(mode="after")
    def _check_quantity_fields(self):
        if self.quantity_type == QuantityType.countable and self.quantity is None:
            raise ValueError("quantity is required when quantity_type is 'countable'")
        if self.quantity_type == QuantityType.uncountable and self.quantity is not None:
            raise ValueError(
                "quantity must be omitted when quantity_type is 'uncountable' — use quantity_note instead"
            )
        return self


class ItemUpdate(BaseModel):
    """All fields optional — PATCH semantics, only provided fields change."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    aliases: list[str] | None = None
    quantity_type: QuantityType | None = None
    quantity: int | None = Field(default=None, ge=0)
    quantity_note: str | None = Field(default=None, max_length=120)
    location: LocationIn | None = None


class ItemOut(BaseModel):
    id: int
    name: str
    description: str | None
    aliases: list[str]
    quantity_type: QuantityType
    quantity: int | None
    quantity_note: str | None
    location: LocationOut | None
    image_path: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, item) -> "ItemOut":
        return cls(
            id=item.id,
            name=item.name,
            description=item.description,
            aliases=[a.alias for a in item.aliases],
            quantity_type=item.quantity_type,
            quantity=item.quantity,
            quantity_note=item.quantity_note,
            location=LocationOut.model_validate(item.location)
            if item.location
            else None,
            image_path=item.image_path,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )


class ItemPage(BaseModel):
    items: list[ItemOut]
    total: int
    limit: int
    offset: int


class BulkDeleteRequest(BaseModel):
    item_ids: list[int] = Field(min_length=1)


class BulkDeleteResult(BaseModel):
    deleted: int
    not_found: list[int]
