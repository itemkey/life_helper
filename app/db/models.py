from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    language_code: Mapped[str | None] = mapped_column(String(16), nullable=True)

    owned_lists: Mapped[list[ShoppingList]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
    )


class ShoppingList(TimestampMixin, Base):
    __tablename__ = "shopping_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    public_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    public_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)

    owner: Mapped[User] = relationship(back_populates="owned_lists")
    items: Mapped[list[ShoppingItem]] = relationship(
        back_populates="shopping_list",
        cascade="all, delete-orphan",
        order_by="ShoppingItem.position",
    )
    members: Mapped[list[ListMember]] = relationship(
        back_populates="shopping_list",
        cascade="all, delete-orphan",
    )


class ShoppingItem(TimestampMixin, Base):
    __tablename__ = "shopping_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    list_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("shopping_lists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(String(255), nullable=False)
    is_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    author_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    shopping_list: Mapped[ShoppingList] = relationship(back_populates="items")
    author: Mapped[User | None] = relationship()


class ListMember(Base):
    __tablename__ = "list_members"
    __table_args__ = (UniqueConstraint("list_id", "user_id", name="uq_list_members_list_id_user_id"),)

    list_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("shopping_lists.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    shopping_list: Mapped[ShoppingList] = relationship(back_populates="members")
    user: Mapped[User] = relationship()
