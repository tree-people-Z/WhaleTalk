"""SQLite 连接参数与结构迁移。

用 ``PRAGMA user_version`` 记录结构版本，迁移按顺序执行且可重复运行。
新增字段时在 ``MIGRATIONS`` 末尾追加即可，不需要再堆临时 ALTER。
"""

from typing import Callable, List, Tuple

from loguru import logger
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

SCHEMA_VERSION = 2

_BUSY_TIMEOUT_MS = 30_000


def apply_sqlite_pragmas(engine: Engine) -> None:
    """开启 WAL 并设置等待超时，降低多线程并发时的 ``database is locked``。"""
    from sqlalchemy import event

    @event.listens_for(engine, 'connect')
    def _set_pragmas(dbapi_connection, _connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute('PRAGMA journal_mode=WAL')
            cursor.execute('PRAGMA synchronous=NORMAL')
            cursor.execute(f'PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}')
            cursor.execute('PRAGMA foreign_keys=ON')
        finally:
            cursor.close()


def _columns(engine: Engine, table: str) -> set:
    try:
        return {col['name'] for col in inspect(engine).get_columns(table)}
    except Exception:  # noqa: BLE001 - 表可能尚未创建
        return set()


def _add_column(engine: Engine, table: str, name: str, ddl: str) -> None:
    if name in _columns(engine, table):
        return
    with engine.begin() as connection:
        connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))
    logger.info(f'数据库迁移: {table}.{name} 已添加')


def _migrate_v1(engine: Engine) -> None:
    # v0 -> v1：评论楼、Agent 会话视频、Agent 事件去重字段
    for name, ddl in (
        ('parent_rpid', 'INTEGER'),
        ('parent_content', 'TEXT'),
        ('thread_root', 'INTEGER'),
        ('target_user', 'VARCHAR(100)'),
    ):
        _add_column(engine, 'comments', name, ddl)
    _add_column(engine, 'agent_sessions', 'videos_json', "TEXT DEFAULT '[]'")
    for name, ddl in (
        ('status', "VARCHAR(20) DEFAULT 'delivered'"),
        ('delivery_count', 'INTEGER DEFAULT 0'),
        ('last_delivered_at', 'DATETIME'),
        ('handled_at', 'DATETIME'),
    ):
        _add_column(engine, 'agent_events', name, ddl)


def _migrate_v2(engine: Engine) -> None:
    """v1 -> v2：新增在线学习相关表。

    ``Base.metadata.create_all`` 会在迁移前建好缺失的表，这里只记录版本。
    """
    return None


# (目标版本, 迁移函数)；函数必须可重复执行。
MIGRATIONS: List[Tuple[int, Callable[[Engine], None]]] = [
    (1, _migrate_v1),
    (2, _migrate_v2),
]


def current_version(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text('PRAGMA user_version')).scalar() or 0)


def migrate_schema(engine: Engine) -> int:
    """执行所有未应用的迁移，返回最终版本号。"""
    version = current_version(engine)
    for target, migrate in MIGRATIONS:
        if version >= target:
            continue
        migrate(engine)
        with engine.begin() as connection:
            connection.execute(text(f'PRAGMA user_version={target}'))
        version = target
        logger.info(f'数据库结构已升级到 v{target}')
    return version
