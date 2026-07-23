from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
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
        foreign_keys="ShoppingList.owner_id",
    )
    list_view_messages: Mapped[list[ListViewMessage]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    banned_memberships: Mapped[list[ListBannedMember]] = relationship(
        back_populates="user",
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
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BYN", server_default="BYN")
    cashbox_holder_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    owner: Mapped[User] = relationship(back_populates="owned_lists", foreign_keys=[owner_id])
    cashbox_holder: Mapped[User | None] = relationship(foreign_keys=[cashbox_holder_id])
    items: Mapped[list[ShoppingItem]] = relationship(
        back_populates="shopping_list",
        cascade="all, delete-orphan",
        order_by="ShoppingItem.position",
    )
    shopping_categories: Mapped[list[ShoppingCategory]] = relationship(
        back_populates="shopping_list",
        cascade="all, delete-orphan",
        order_by="ShoppingCategory.position",
    )
    members: Mapped[list[ListMember]] = relationship(
        back_populates="shopping_list",
        cascade="all, delete-orphan",
    )
    view_messages: Mapped[list[ListViewMessage]] = relationship(
        back_populates="shopping_list",
        cascade="all, delete-orphan",
    )
    banned_members: Mapped[list[ListBannedMember]] = relationship(
        back_populates="shopping_list",
        cascade="all, delete-orphan",
    )
    contributions: Mapped[list[Contribution]] = relationship(
        back_populates="shopping_list",
        cascade="all, delete-orphan",
    )
    expenses: Mapped[list[Expense]] = relationship(
        back_populates="shopping_list",
        cascade="all, delete-orphan",
    )
    expense_categories: Mapped[list[ExpenseCategory]] = relationship(
        back_populates="shopping_list",
        cascade="all, delete-orphan",
        order_by="ExpenseCategory.position",
    )


class ShoppingItem(TimestampMixin, Base):
    __tablename__ = "shopping_items"
    __table_args__ = (
        CheckConstraint("scope in ('common', 'personal')", name="ck_shopping_items_scope"),
        CheckConstraint(
            "(scope = 'common' and personal_owner_id is null) or "
            "(scope = 'personal' and personal_owner_id is not null)",
            name="ck_shopping_items_scope_owner",
        ),
    )

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
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="common", server_default="common")
    personal_owner_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    category_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("shopping_categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    shopping_list: Mapped[ShoppingList] = relationship(back_populates="items")
    author: Mapped[User | None] = relationship(foreign_keys=[author_id])
    personal_owner: Mapped[User | None] = relationship(foreign_keys=[personal_owner_id])
    category: Mapped[ShoppingCategory | None] = relationship(back_populates="items")
    expenses: Mapped[list[Expense]] = relationship(back_populates="item")
    expense_links: Mapped[list[ExpenseItem]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
    )


class ShoppingCategory(TimestampMixin, Base):
    __tablename__ = "shopping_categories"
    __table_args__ = (
        CheckConstraint("scope in ('common', 'personal')", name="ck_shopping_categories_scope"),
        CheckConstraint("accounting_mode in ('per_item', 'receipt')", name="ck_shopping_categories_accounting_mode"),
        CheckConstraint(
            "(scope = 'common' and owner_id is null) or "
            "(scope = 'personal' and owner_id is not null)",
            name="ck_shopping_categories_scope_owner",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    list_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("shopping_lists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="common", server_default="common")
    owner_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    accounting_mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="per_item",
        server_default="per_item",
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    shopping_list: Mapped[ShoppingList] = relationship(back_populates="shopping_categories")
    owner: Mapped[User | None] = relationship(foreign_keys=[owner_id])
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    items: Mapped[list[ShoppingItem]] = relationship(back_populates="category", order_by="ShoppingItem.position")


class ListViewMessage(TimestampMixin, Base):
    __tablename__ = "list_view_messages"

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
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    message_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    shopping_list: Mapped[ShoppingList] = relationship(back_populates="view_messages")
    user: Mapped[User] = relationship(back_populates="list_view_messages")


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


class ListBannedMember(Base):
    __tablename__ = "list_banned_members"
    __table_args__ = (UniqueConstraint("list_id", "user_id", name="uq_list_banned_members_list_id_user_id"),)

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
    banned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    shopping_list: Mapped[ShoppingList] = relationship(back_populates="banned_members")
    user: Mapped[User] = relationship(back_populates="banned_memberships")


class Contribution(TimestampMixin, Base):
    __tablename__ = "contributions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    list_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("shopping_lists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    shopping_list: Mapped[ShoppingList] = relationship(back_populates="contributions")
    user: Mapped[User] = relationship(foreign_keys=[user_id])
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])


class Expense(TimestampMixin, Base):
    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint("source in ('cashbox', 'personal')", name="ck_expenses_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    list_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("shopping_lists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    payer_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    item_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("shopping_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    category_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("expense_categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    shopping_list: Mapped[ShoppingList] = relationship(back_populates="expenses")
    payer: Mapped[User] = relationship(foreign_keys=[payer_id])
    item: Mapped[ShoppingItem | None] = relationship(back_populates="expenses")
    category: Mapped[ExpenseCategory | None] = relationship(back_populates="expenses")
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    shares: Mapped[list[ExpenseShare]] = relationship(
        back_populates="expense",
        cascade="all, delete-orphan",
        order_by="ExpenseShare.user_id",
    )
    item_links: Mapped[list[ExpenseItem]] = relationship(
        back_populates="expense",
        cascade="all, delete-orphan",
        order_by="ExpenseItem.item_id",
    )


class ExpenseCategory(TimestampMixin, Base):
    __tablename__ = "expense_categories"
    __table_args__ = (
        CheckConstraint("default_split in ('all', 'selected', 'me')", name="ck_expense_categories_default_split"),
        UniqueConstraint("list_id", "title", name="uq_expense_categories_list_id_title"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    list_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("shopping_lists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    default_split: Mapped[str] = mapped_column(String(16), nullable=False, default="selected", server_default="selected")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    shopping_list: Mapped[ShoppingList] = relationship(back_populates="expense_categories")
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    expenses: Mapped[list[Expense]] = relationship(back_populates="category")


class ExpenseShare(Base):
    __tablename__ = "expense_shares"

    expense_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("expenses.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)

    expense: Mapped[Expense] = relationship(back_populates="shares")
    user: Mapped[User] = relationship()


class ExpenseItem(Base):
    __tablename__ = "expense_items"

    expense_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("expenses.id", ondelete="CASCADE"),
        primary_key=True,
    )
    item_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("shopping_items.id", ondelete="CASCADE"),
        primary_key=True,
    )

    expense: Mapped[Expense] = relationship(back_populates="item_links")
    item: Mapped[ShoppingItem] = relationship(back_populates="expense_links")
