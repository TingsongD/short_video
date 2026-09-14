"""YouTube Data API quota budget. search.list is the expensive call (100 units);
everything else is 1 unit. Degrade to channel-only scans when search is unaffordable."""

COSTS = {"search": 100, "channels": 1, "playlistItems": 1, "videos": 1}


class QuotaExhausted(Exception):
    pass


class QuotaManager:
    def __init__(self, budget):
        self.budget = int(budget)
        self.used = 0

    def cost(self, endpoint):
        return COSTS.get(endpoint, 1)

    def can_afford(self, endpoint):
        return self.used + self.cost(endpoint) <= self.budget

    def charge(self, endpoint):
        if not self.can_afford(endpoint):
            raise QuotaExhausted(
                f"{endpoint} needs {self.cost(endpoint)} units; "
                f"{self.used}/{self.budget} used"
            )
        self.used += self.cost(endpoint)
