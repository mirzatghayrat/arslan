"""Arslan — Tag-based template matcher using Jaccard similarity."""
from __future__ import annotations

from typing import Any


class TagMatcher:
    """Scores and ranks templates by tag similarity (Jaccard index)."""

    def score(self, query_tags: list[str], template_tags: list[str]) -> float:
        """Compute Jaccard similarity between two tag lists (case-insensitive).

        Returns 0.0 if either list is empty.
        """
        if not query_tags or not template_tags:
            return 0.0

        query_set = {t.lower() for t in query_tags}
        template_set = {t.lower() for t in template_tags}

        intersection = query_set & template_set
        union = query_set | template_set

        if not union:
            return 0.0

        return len(intersection) / len(union)

    def rank(
        self,
        query_tags: list[str],
        templates: list[dict[str, Any]],
        min_score: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Score each template dict (must have 'tags' key), filter by min_score,
        sort descending by score, and add '_score' to each result.
        """
        scored = []
        for template in templates:
            template_tags = template.get("tags", [])
            s = self.score(query_tags, template_tags)
            if s >= min_score:
                result = dict(template)
                result["_score"] = s
                scored.append(result)

        scored.sort(key=lambda x: x["_score"], reverse=True)
        return scored
