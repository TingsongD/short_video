"""Server-sent events (F27): ordered, replayable, disconnect-safe.

Events come from the durable event log — a dropped connection never
cancels work, and `Last-Event-ID` resumes exactly where it left off.
"""
import asyncio
import json


def sse_frames(events, keepalive=True):
    """Render ordered events as SSE frames; each carries `id: seq` so
    clients can resume via Last-Event-ID."""
    out = []
    for e in events:
        out.append(f"id: {e['seq']}\nevent: factory\n"
                   f"data: {json.dumps({'type':e['type'],'stream':e.get('stream'),'body':json.loads(e['body'])})}\n\n")
    if keepalive:
        out.append(": keepalive\n\n")
    return out


async def event_stream(services, stream, after, follow=False,
                       poll_s=0.25, max_polls=40):
    """Backlog first (cursor replay), then keepalives; `follow` keeps
    polling for new events, default returns a finite reconnect-safe
    response suitable for tests and dashboards alike."""
    sent = after
    for e in services.events_since(stream, sent):
        yield f"id: {e['seq']}\nevent: factory\ndata: {json.dumps({'type':e['type'],'stream':e.get('stream'),'body':json.loads(e['body'])})}\n\n"
        sent = e["seq"]
    yield ": keepalive\n\n"
    if follow:
        for _ in range(max_polls):
            await asyncio.sleep(poll_s)
            new = services.events_since(stream, sent)
            if not new:
                yield ": keepalive\n\n"
                continue
            for e in new:
                yield f"id: {e['seq']}\nevent: factory\n" \
                      f"data: {json.dumps({'type':e['type'],'stream':e.get('stream'),'body':json.loads(e['body'])})}\n\n"
                sent = e["seq"]
