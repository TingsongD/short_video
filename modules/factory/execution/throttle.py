"""A narrowly evidenced retry: synchronous analysis HTTP 429, never unknown."""
import json
from datetime import datetime, timezone

BACKOFF = (30, 90)  # two retries, then an actionable pause; survives restarts


def rejection(db, attempt):
    if not attempt or attempt['status'] != 'failed' or attempt['remote_id']:
        return None
    reservation = db.conn.execute('SELECT status FROM reservations WHERE id=?', (attempt['reservation_id'],)).fetchone()
    if not reservation or reservation['status'] != 'released':
        return None
    row = db.conn.execute("SELECT body,created_at FROM events WHERE stream=? AND type='submit_failed' ORDER BY seq DESC LIMIT 1",
                          ('attempt:' + attempt['id'],)).fetchone()
    if not row:
        return None
    proof = json.loads(row['body'])
    if proof.get('cause') == 'analysis_http_error' and proof.get('http_status') == 429 and proof.get('class') == 'pre_acceptance':
        return row['created_at']
    return None


def wait_seconds(db, attempt, now):
    rejected_at = rejection(db, attempt)
    if not rejected_at or attempt['attempt_seq'] > len(BACKOFF):
        return None
    since = datetime.fromisoformat(rejected_at.replace('Z', '+00:00'))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0, BACKOFF[attempt['attempt_seq'] - 1] - (now - since).total_seconds())
