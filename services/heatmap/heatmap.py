from __future__ import annotations

from typing import Any


class HeatmapGrid:
    def __init__(self, columns: int, rows: int) -> None:
        if columns < 1 or rows < 1:
            raise ValueError("heatmap dimensions must be positive")
        self.columns = columns
        self.rows = rows
        self.counts = [[0 for _ in range(columns)] for _ in range(rows)]
        self.samples = 0

    def add(self, x: float, y: float) -> None:
        x = min(1.0, max(0.0, float(x)))
        y = min(1.0, max(0.0, float(y)))
        column = min(self.columns - 1, int(x * self.columns))
        row = min(self.rows - 1, int(y * self.rows))
        self.counts[row][column] += 1
        self.samples += 1

    def snapshot(self) -> dict[str, Any]:
        maximum = max((max(row) for row in self.counts), default=0)
        normalized = [
            [round(value / maximum, 4) if maximum else 0.0 for value in row]
            for row in self.counts
        ]
        return {
            "columns": self.columns,
            "rows": self.rows,
            "samples": self.samples,
            "max_cell_count": maximum,
            "counts": self.counts,
            "normalized": normalized,
        }
