from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, BigInteger, Text
from sqlalchemy.orm import relationship
from database import Base
import datetime


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True)
    name = Column(String)
    role = Column(String, default="viewer")

    transactions = relationship("Transaction", back_populates="user", foreign_keys="Transaction.user_id")
    created_transactions = relationship("Transaction", back_populates="created_by_user", foreign_keys="Transaction.created_by")


class Collection(Base):
    __tablename__ = "collections"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    collection_type = Column(String, default="general")
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.datetime.now)

    transactions = relationship("Transaction", back_populates="collection")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    payer_name = Column(String, nullable=True)
    collection_id = Column(Integer, ForeignKey("collections.id"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    type = Column(String)
    amount = Column(Float)
    category = Column(String)
    description = Column(Text, nullable=True)
    date = Column(DateTime, default=datetime.datetime.now)
    photo_path = Column(String, nullable=True)

    user = relationship("User", back_populates="transactions", foreign_keys=[user_id])
    created_by_user = relationship("User", back_populates="created_transactions", foreign_keys=[created_by])
    collection = relationship("Collection", back_populates="transactions")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String)
    entity_type = Column(String)
    entity_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)

    user = relationship("User")


class UsageLog(Base):
    __tablename__ = "usage_log"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    telegram_id = Column(BigInteger, nullable=True)
    user_name = Column(String, nullable=True)
    action = Column(String, nullable=False)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.now)

    user = relationship("User")
