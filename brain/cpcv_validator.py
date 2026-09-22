"""
brain/cpcv_validator.py — Combinatorial Purged Cross-Validation (CPCV)

Implements Purged & Embargoed Cross-Validation for financial time series data
to prevent look-ahead bias and data leakage.
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Generator, List, Tuple

class CombinatorialPurgedCV:
    """
    Combinatorial Purged Cross-Validation (CPCV)
    
    Parameters
    ----------
    n_splits : int
        Number of equal folds to divide the time series into.
    n_test_folds : int
        Number of folds used for testing in each combination.
    pct_embargo : float
        Percentage of samples following a test fold to embargo (zero out).
    """

    def __init__(self, n_splits: int = 5, n_test_folds: int = 2, pct_embargo: float = 0.01) -> None:
        self.n_splits = n_splits
        self.n_test_folds = n_test_folds
        self.pct_embargo = pct_embargo

    def _get_fold_bounds(self, n_samples: int) -> List[Tuple[int, int]]:
        fold_size = n_samples // self.n_splits
        bounds = []
        for i in range(self.n_splits):
            start = i * fold_size
            end = (i + 1) * fold_size if i < self.n_splits - 1 else n_samples
            bounds.append((start, end))
        return bounds

    def split(self, X: np.ndarray, y: np.ndarray = None) -> Generator[Tuple[np.ndarray, np.ndarray], None, None]:
        n_samples = len(X)
        bounds = self._get_fold_bounds(n_samples)
        embargo_offset = int(n_samples * self.pct_embargo)

        import itertools
        fold_indices = list(range(self.n_splits))
        
        # Combinations of test folds
        for test_fold_combo in itertools.combinations(fold_indices, self.n_test_folds):
            test_indices = []
            embargo_indices = set()

            for f_idx in test_fold_combo:
                start, end = bounds[f_idx]
                test_indices.extend(range(start, end))
                
                # Apply embargo period right after test fold
                for emb in range(end, min(end + embargo_offset, n_samples)):
                    embargo_indices.add(emb)

            test_set = np.array(sorted(test_indices))
            
            # Train set excludes test indices AND embargoed indices
            train_indices = [
                i for i in range(n_samples) 
                if i not in test_set and i not in embargo_indices
            ]
            train_set = np.array(train_indices)

            yield train_set, test_set
