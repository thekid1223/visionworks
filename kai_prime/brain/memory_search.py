"""Memory Search — FTS5 full-text search with BM25 ranking for cross-session recall."""
from __future__ import annotations
import json, logging, re, sqlite3, threading, time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("kai_prime.memory_search")


@dataclass
class MemoryFragment:
    id: str = ""
    session_id: str = ""
    timestamp: str = ""
    user_input: str = ""
    kai_response: str = ""
    context: str = ""
    tags: list[str] = field(default_factory=list)
    importance: float = 1.0
    insights: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "session_id": self.session_id, "timestamp": self.timestamp,
            "user_input": self.user_input, "kai_response": self.kai_response,
            "context": self.context, "tags": ",".join(self.tags),
            "importance": self.importance, "insights": json.dumps(self.insights),
        }


class MemorySearch:
    """FTS5-powered cross-session conversation search with BM25 ranking."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.db_path = workspace / "kai_prime_data" / "memory_search.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    id, session_id, timestamp, user_input, kai_response, context, tags,
                    importance, insights,
                    tokenize = 'porter unicode61'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_meta (
                    id TEXT PRIMARY KEY, session_id TEXT, timestamp TEXT,
                    importance REAL, tags TEXT, insights TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_session ON memory_meta(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_ts ON memory_meta(timestamp)")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path), timeout=5)

    def store(self, fragment: MemoryFragment):
        d = fragment.to_dict()
        with self._lock, self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO memory_fts
                (id, session_id, timestamp, user_input, kai_response, context, tags, importance, insights)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (d["id"], d["session_id"], d["timestamp"], d["user_input"],
                  d["kai_response"], d["context"], d["tags"], d["importance"], d["insights"]))
            conn.execute("""
                INSERT OR REPLACE INTO memory_meta (id, session_id, timestamp, importance, tags, insights)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (d["id"], d["session_id"], d["timestamp"], d["importance"], d["tags"], d["insights"]))

    def search(self, query: str, limit: int = 10, days_back: int = 90) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
        keywords = self._extract_keywords(query)
        if not keywords:
            return []
        fts_query = " OR ".join(keywords)
        try:
            with self._conn() as conn:
                rows = conn.execute("""
                    SELECT m.*, highlight(memory_fts, 3, '<mark>', '</mark>') as hl_input,
                           highlight(memory_fts, 4, '<mark>', '</mark>') as hl_response,
                           bm25(memory_fts) as score
                    FROM memory_fts m
                    WHERE memory_fts MATCH ? AND timestamp > ?
                    ORDER BY bm25(memory_fts), importance DESC
                    LIMIT ?
                """, (fts_query, cutoff, limit)).fetchall()
            return [self._row_to_dict(r, hl=True) for r in rows]
        except Exception as e:
            log.warning("FTS5 search failed: %s", e)
            return []

    def find_similar(self, context: str, limit: int = 5) -> list[dict]:
        keywords = self._extract_keywords(context)
        if not keywords:
            return []
        return self.search(" OR ".join(keywords), limit=limit, days_back=180)

    def recent_conversations(self, limit: int = 20) -> list[dict]:
        try:
            with self._conn() as conn:
                rows = conn.execute("""
                    SELECT m.* FROM memory_fts m
                    ORDER BY timestamp DESC LIMIT ?
                """, (limit,)).fetchall()
            return [self._row_to_dict(r) for r in rows]
        except Exception:
            return []

    def get_insights(self, days_back: int = 30) -> dict:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
        try:
            with self._conn() as conn:
                total = conn.execute(
                    "SELECT COUNT(*) FROM memory_meta WHERE timestamp > ?", (cutoff,)
                ).fetchone()[0]
                tags = conn.execute("""
                    SELECT tags, COUNT(*) as c FROM memory_meta
                    WHERE timestamp > ? AND tags != '' GROUP BY tags ORDER BY c DESC LIMIT 10
                """, (cutoff,)).fetchall()
                insights_raw = conn.execute("""
                    SELECT insights FROM memory_meta
                    WHERE timestamp > ? AND insights != '[]' ORDER BY timestamp DESC LIMIT 20
                """, (cutoff,)).fetchall()
            all_insights = []
            for row in insights_raw:
                try:
                    all_insights.extend(json.loads(row[0]))
                except Exception:
                    pass
            counts = Counter(all_insights)
            return {
                "total_memories": total,
                "common_tags": [{"tag": r[0], "count": r[1]} for r in tags],
                "top_insights": [{"insight": k, "count": v} for k, v in counts.most_common(5)],
            }
        except Exception:
            return {"total_memories": 0, "common_tags": [], "top_insights": []}

    def cleanup(self, days_to_keep: int = 365):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_to_keep)).isoformat()
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM memory_fts WHERE timestamp < ?", (cutoff,))
            conn.execute("DELETE FROM memory_meta WHERE timestamp < ?", (cutoff,))

    def count(self) -> int:
        try:
            with self._conn() as conn:
                return conn.execute("SELECT COUNT(*) FROM memory_meta").fetchone()[0]
        except Exception:
            return 0

    def _row_to_dict(self, row, hl: bool = False) -> dict:
        d = {
            "id": row[0], "session_id": row[1], "timestamp": row[2],
            "user_input": row[3], "kai_response": row[4], "context": row[5],
            "tags": row[6].split(",") if row[6] else [],
            "importance": row[7],
            "insights": json.loads(row[8]) if row[8] else [],
        }
        if hl:
            d["highlighted_input"] = row[9] or row[3]
            d["highlighted_response"] = row[10] or row[4]
            d["relevance_score"] = row[11]
        return d

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        stopwords = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
            "of", "with", "by", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "must", "can", "i", "you", "he", "she",
            "it", "we", "they", "me", "him", "her", "us", "them", "my", "your",
            "his", "its", "our", "their", "what", "which", "who", "whom",
            "this", "that", "these", "those", "get", "got", "like", "just",
            "about", "up", "out", "if", "so", "no", "not", "yes",
        }
        words = re.findall(r"\b\w+\b", text.lower())
        return [w for w in words if len(w) > 2 and w not in stopwords][:8]
