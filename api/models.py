"""SQLAlchemy 2.x declarative models mirroring db/001_schema.sql."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AppUser(Base):
    __tablename__ = "app_users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    seed_credits_used_today: Mapped[int] = mapped_column(Integer, default=0)
    seed_credits_reset_on: Mapped[dt.date] = mapped_column(Date)
    timezone: Mapped[str] = mapped_column(String, default="America/New_York")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class SectorBenchmark(Base):
    __tablename__ = "sector_benchmarks"
    sector: Mapped[str] = mapped_column(String, primary_key=True)
    benchmark_ticker: Mapped[str] = mapped_column(String)


class Ticker(Base):
    __tablename__ = "tickers"
    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(String)
    instrument_class: Mapped[str] = mapped_column(String, default="stock")
    sector: Mapped[str | None] = mapped_column(
        String, ForeignKey("sector_benchmarks.sector")
    )
    benchmark_ticker: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="seeding")
    last_watched_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class SymbolCatalog(Base):
    __tablename__ = "symbol_catalog"
    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(String)
    exchange: Mapped[str | None] = mapped_column(String)
    type: Mapped[str | None] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    refcount: Mapped[int] = mapped_column(Integer, default=0)
    refreshed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    ticker: Mapped[str] = mapped_column(
        String, ForeignKey("tickers.ticker"), primary_key=True
    )
    added_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    pinned_unread: Mapped[bool] = mapped_column(Boolean, default=False)


class TickerDailyBar(Base):
    __tablename__ = "ticker_daily_bar"
    ticker: Mapped[str] = mapped_column(
        String, ForeignKey("tickers.ticker", ondelete="CASCADE"), primary_key=True
    )
    bar_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int | None] = mapped_column(BigInteger)


class TickerBaseline(Base):
    __tablename__ = "ticker_baseline"
    ticker: Mapped[str] = mapped_column(
        String, ForeignKey("tickers.ticker", ondelete="CASCADE"), primary_key=True
    )
    sample_days: Mapped[int] = mapped_column(Integer, default=0)
    mean_ret: Mapped[float | None] = mapped_column(Float)
    var_stock: Mapped[float | None] = mapped_column(Float)
    mean_bench: Mapped[float | None] = mapped_column(Float)
    var_bench: Mapped[float | None] = mapped_column(Float)
    cov: Mapped[float | None] = mapped_column(Float)
    beta_raw: Mapped[float | None] = mapped_column(Float)
    beta_used: Mapped[float | None] = mapped_column(Float)
    r2: Mapped[float | None] = mapped_column(Float)
    mean_excess: Mapped[float | None] = mapped_column(Float)
    var_excess: Mapped[float | None] = mapped_column(Float)
    sigma_idio: Mapped[float | None] = mapped_column(Float)
    sigma_mad: Mapped[float | None] = mapped_column(Float)
    adv20: Mapped[float | None] = mapped_column(Float)
    wk52_high: Mapped[float | None] = mapped_column(Float)
    wk52_low: Mapped[float | None] = mapped_column(Float)
    recent_daily: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    residual_hist: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    last_bar_date: Mapped[dt.date | None] = mapped_column(Date)
    frozen_reason: Mapped[str | None] = mapped_column(String)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class EarningsDate(Base):
    __tablename__ = "earnings_dates"
    ticker: Mapped[str] = mapped_column(
        String, ForeignKey("tickers.ticker", ondelete="CASCADE"), primary_key=True
    )
    event_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    source: Mapped[str] = mapped_column(String)


class CorporateAction(Base):
    __tablename__ = "corporate_actions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(
        String, ForeignKey("tickers.ticker", ondelete="CASCADE")
    )
    detected_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    effective_date: Mapped[dt.date] = mapped_column(Date)
    observed_ratio: Mapped[float] = mapped_column(Float)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)


class TickerLatest(Base):
    __tablename__ = "ticker_latest"
    ticker: Mapped[str] = mapped_column(
        String, ForeignKey("tickers.ticker", ondelete="CASCADE"), primary_key=True
    )
    price: Mapped[float | None] = mapped_column(Float)
    prev_close: Mapped[float | None] = mapped_column(Float)
    day_volume: Mapped[int | None] = mapped_column(BigInteger)
    is_extended_hours: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    bar_date: Mapped[dt.date | None] = mapped_column(Date)
    extended_price: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String, default="ok")
    pending_price: Mapped[float | None] = mapped_column(Float)
    pending_since: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    pending_cycles: Mapped[int] = mapped_column(Integer, default=0)


class WatchlistSnapshot(Base):
    __tablename__ = "watchlist_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "ticker"],
            ["watchlist_items.user_id", "watchlist_items.ticker"],
            ondelete="CASCADE",
        ),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    last_seen_price: Mapped[float] = mapped_column(Float)
    last_seen_bench: Mapped[float] = mapped_column(Float)
    last_seen_bench_ticker: Mapped[str] = mapped_column(String)
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    is_initial: Mapped[bool] = mapped_column(Boolean, default=True)


class DigestFeedback(Base):
    __tablename__ = "digest_feedback"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    ticker: Mapped[str] = mapped_column(String)
    tier: Mapped[str] = mapped_column(String)
    attention: Mapped[float] = mapped_column(Float)
    shown_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    clicked_through: Mapped[bool] = mapped_column(Boolean, default=False)
    dismissed_fast: Mapped[bool] = mapped_column(Boolean, default=False)
    thumb: Mapped[int | None] = mapped_column(SmallInteger)


class JobRun(Base):
    __tablename__ = "job_run"
    run_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String)
    credits_spent: Mapped[int] = mapped_column(Integer, default=0)


class JobItem(Base):
    __tablename__ = "job_item"
    run_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    refcount: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String)


class ProviderResponseCache(Base):
    __tablename__ = "provider_response_cache"
    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    run_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class QuotaLedger(Base):
    __tablename__ = "quota_ledger"
    partition: Mapped[str] = mapped_column(String, primary_key=True)
    usage_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    spent: Mapped[int] = mapped_column(Integer, default=0)
