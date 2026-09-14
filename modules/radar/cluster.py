"""Group breakout videos into topic clusters. A cluster is confirmed when
>= cluster_min_channels DISTINCT channels spike on the same topic."""
import re

STOPWORDS = {
    "the", "a", "an", "i", "you", "my", "your", "this", "that", "it", "is",
    "are", "was", "were", "to", "in", "for", "on", "of", "and", "or", "how",
    "with", "do", "not", "dont", "can", "will", "just", "all", "but", "be",
    "have", "has", "from", "at", "by", "if", "so", "no", "what", "when",
    "why", "who", "which", "their", "they", "them", "me", "we", "us", "its",
    "been", "had", "did", "get", "got", "than", "into", "these", "those",
    "very", "more", "most", "about", "up", "out", "one", "also", "even",
    "after", "before", "here", "there", "then", "new", "now", "way", "may",
    "like", "over", "only", "any", "such", "make", "each", "re", "ve", "ll",
    "don", "t", "s", "m", "d", "that",
}


def _tokens(text):
    return {w for w in re.findall(r"[a-z0-9]+", text.lower())
            if w not in STOPWORDS and len(w) > 2}


def topic_key(title, niche_keywords):
    """Deterministic topic label: the niche keyword sharing the most title
    tokens; fallback to the two longest content tokens so unrelated spikes
    don't merge into one blob."""
    toks = _tokens(title)
    best, best_overlap = None, 0
    for kw in niche_keywords:
        overlap = len(toks & _tokens(kw))
        if overlap > best_overlap:
            best, best_overlap = kw, overlap
    if best:
        return best
    top = sorted(toks, key=lambda t: (-len(t), t))[:2]
    return "misc:" + "_".join(top) if top else "misc"


def group_clusters(videos, niche_keywords):
    groups = {}
    for v in videos:
        groups.setdefault(topic_key(v["title"], niche_keywords), []).append(v)
    return groups


def cluster_confirmed(videos, min_channels):
    return len({v["channel_id"] for v in videos}) >= min_channels
