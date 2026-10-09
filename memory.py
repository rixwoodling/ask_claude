#!/usr/bin/env python3
"""SQLite-backed conversation memory for the Claude assistant."""

import sqlite3
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "memory.db"


def _connect():
    """Open a connection to the memory database."""
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def initialize():
    """Create the memory database and tables if they do not exist."""
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL
            )
            """
        )
        connection.commit()


def add_message(role, content):
    """Store a conversation message."""
    if not role:
        raise ValueError("role is required")

    if content is None:
        raise ValueError("content is required")

    initialize()

    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")

    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO messages (timestamp, role, content)
            VALUES (?, ?, ?)
            """,
            (timestamp, role, str(content)),
        )
        connection.commit()

        return cursor.lastrowid


def get_last_message(role=None):
    """Return the most recent message, optionally filtered by role."""
    initialize()

    with _connect() as connection:
        if role:
            row = connection.execute(
                """
                SELECT id, timestamp, role, content
                FROM messages
                WHERE role = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (role,),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT id, timestamp, role, content
                FROM messages
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()

    return dict(row) if row else None


def get_recent_messages(limit=10):
    """Return the most recent messages in chronological order."""
    initialize()

    if not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")

    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, timestamp, role, content
            FROM messages
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in reversed(rows)]


def clear():
    """Delete all stored conversation messages."""
    initialize()

    with _connect() as connection:
        connection.execute("DELETE FROM messages")
        connection.commit()


if __name__ == "__main__":
    initialize()
    print(f"Memory database: {DATABASE}")
