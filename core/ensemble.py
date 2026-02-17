"""
Ensemble Signal Aggregator with regime-aware weighting.

Combines signals from multiple strategies using a 2-of-3 consensus
rule, where strategy weights are modulated by the current market regime.

Reference: doc/Crypto Algo Trading System Research.md (Section 2)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from core.regime_detector import Regime, RegimeState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Strategy-to-regime affinity weights (0.0–1.0)
# ---------------------------------------------------------------------------

# Each strategy gets a weight based on how well it performs in each regime.
# These are the default weights; can be overridden via config.
DEFAULT_AFFINITY: dict[Regime, dict[str, float]] = {
    Regime.TRENDING_STRONG: {
        "trend_ema": 1.0,
        "supertrend": 1.0,
        "turtle": 0.9,
        "triple_momentum": 0.8,
        "squeeze_breakout": 0.6,
        "macd_crossover": 0.7,
        "mean_reversion_bb": 0.1,
        "rsi_divergence": 0.1,
        "vwap_bounce": 0.2,
        "volatility_hunter": 0.5,
    },
    Regime.TRENDING_WEAK: {
        "trend_ema": 0.7,
        "supertrend": 0.7,
        "turtle": 0.5,
        "triple_momentum": 0.6,
        "squeeze_breakout": 0.8,
        "macd_crossover": 0.7,
        "mean_reversion_bb": 0.3,
        "rsi_divergence": 0.3,
        "vwap_bounce": 0.4,
        "volatility_hunter": 0.6,
    },
    Regime.MEAN_REVERTING: {
        "trend_ema": 0.1,
        "supertrend": 0.2,
        "turtle": 0.1,
        "triple_momentum": 0.2,
        "squeeze_breakout": 0.3,
        "macd_crossover": 0.3,
        "mean_reversion_bb": 1.0,
        "rsi_divergence": 0.9,
        "vwap_bounce": 0.8,
        "volatility_hunter": 0.4,
    },
    Regime.RANDOM_WALK: {
        "trend_ema": 0.0,
        "supertrend": 0.0,
        "turtle": 0.0,
        "triple_momentum": 0.0,
        "squeeze_breakout": 0.1,
        "macd_crossover": 0.0,
        "mean_reversion_bb": 0.2,
        "rsi_divergence": 0.1,
        "vwap_bounce": 0.1,
        "volatility_hunter": 0.1,
    },
}


@dataclass
class StrategyVote:
    """A single strategy's signal with its regime-adjusted weight."""

    strategy_name: str
    action: str  # "OPEN_LONG", "CLOSE_LONG", "HOLD", etc.
    confidence: float  # strategy's own confidence (0.0–1.0)
    regime_weight: float  # affinity weight for current regime
    extra: dict = field(default_factory=dict)  # stop, tp, atr, etc.

    @property
    def weighted_score(self) -> float:
        return self.confidence * self.regime_weight


@dataclass
class EnsembleSignal:
    """Aggregated signal from the ensemble."""

    action: str  # final consensus action
    confidence: float  # aggregated confidence
    votes_for: int  # strategies voting for this action
    votes_total: int  # total strategies that voted (non-HOLD)
    consensus_met: bool  # whether the threshold was reached
    regime: Regime
    strategy_votes: list[StrategyVote]
    extra: dict = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"<Ensemble {self.action} conf={self.confidence:.2f} "
            f"votes={self.votes_for}/{self.votes_total} "
            f"consensus={'✓' if self.consensus_met else '✗'}>"
        )


class Ensemble:
    """
    Regime-aware strategy signal aggregator.

    Collects signals from multiple strategies, weights them by regime
    affinity, and applies a consensus threshold to produce a final signal.

    Args:
        consensus_threshold: Minimum number of strategies that must agree
        min_weighted_confidence: Minimum weighted confidence to act
        affinity_map: Strategy-to-regime affinity weights (override defaults)
    """

    def __init__(
        self,
        consensus_threshold: int = 2,
        min_weighted_confidence: float = 0.3,
        affinity_map: Optional[dict[Regime, dict[str, float]]] = None,
    ):
        self.consensus_threshold = consensus_threshold
        self.min_weighted_confidence = min_weighted_confidence
        self.affinity_map = affinity_map or DEFAULT_AFFINITY

    def aggregate(
        self,
        signals: dict[str, object],
        regime_state: RegimeState,
    ) -> EnsembleSignal:
        """
        Aggregate strategy signals into a single ensemble decision.

        Args:
            signals: Dict of {strategy_name: StrategySignal} from each strategy.
                     Each signal should have .action, .extra, optionally .confidence
            regime_state: Current regime state from the regime detector.

        Returns:
            EnsembleSignal with the consensus-based decision.
        """
        votes: list[StrategyVote] = []

        for strat_name, signal in signals.items():
            action = getattr(signal, "action", "HOLD")
            confidence = getattr(signal, "confidence", 0.5)
            extra = getattr(signal, "extra", {}) or {}

            # Get regime affinity weight
            regime_weights = self.affinity_map.get(regime_state.regime, {})
            # Normalize the strategy name to match affinity keys
            norm_name = self._normalize_strategy_name(strat_name)
            regime_weight = regime_weights.get(norm_name, 0.3)  # default 0.3

            vote = StrategyVote(
                strategy_name=strat_name,
                action=action,
                confidence=confidence,
                regime_weight=regime_weight,
                extra=extra,
            )
            votes.append(vote)

        # Count votes by action (excluding HOLD)
        action_scores: dict[str, list[StrategyVote]] = {}
        for vote in votes:
            if vote.action == "HOLD":
                continue
            action_scores.setdefault(vote.action, []).append(vote)

        if not action_scores:
            # Everyone says HOLD
            return EnsembleSignal(
                action="HOLD",
                confidence=0.0,
                votes_for=0,
                votes_total=0,
                consensus_met=False,
                regime=regime_state.regime,
                strategy_votes=votes,
            )

        # Find the action with the most / highest-weighted votes
        best_action = None
        best_score = 0.0
        best_voters: list[StrategyVote] = []

        for action, voters in action_scores.items():
            total_score = sum(v.weighted_score for v in voters)
            if total_score > best_score:
                best_score = total_score
                best_action = action
                best_voters = voters

        # Check for conflict: if there are opposing actions (BUY vs SELL)
        has_buy = any(
            a in ("OPEN_LONG",) for a in action_scores
        )
        has_sell = any(
            a in ("OPEN_SHORT", "CLOSE_LONG") for a in action_scores
        )

        if has_buy and has_sell:
            # Conflict → HOLD unless one side has overwhelming consensus
            buy_score = sum(
                v.weighted_score
                for a, vs in action_scores.items()
                if a == "OPEN_LONG"
                for v in vs
            )
            sell_score = sum(
                v.weighted_score
                for a, vs in action_scores.items()
                if a in ("OPEN_SHORT", "CLOSE_LONG")
                for v in vs
            )

            if buy_score > sell_score * 2:
                best_action = "OPEN_LONG"
                best_voters = action_scores.get("OPEN_LONG", [])
            elif sell_score > buy_score * 2:
                # Pick the dominant sell action
                if "CLOSE_LONG" in action_scores:
                    best_action = "CLOSE_LONG"
                    best_voters = action_scores["CLOSE_LONG"]
                else:
                    best_action = "OPEN_SHORT"
                    best_voters = action_scores.get("OPEN_SHORT", [])
            else:
                logger.info(
                    "Ensemble conflict: BUY(%.2f) vs SELL(%.2f) → HOLD",
                    buy_score, sell_score,
                )
                return EnsembleSignal(
                    action="HOLD",
                    confidence=0.0,
                    votes_for=0,
                    votes_total=len(action_scores),
                    consensus_met=False,
                    regime=regime_state.regime,
                    strategy_votes=votes,
                )

        votes_for = len(best_voters)
        votes_total = sum(len(vs) for vs in action_scores.values())

        # Check consensus threshold
        consensus_met = votes_for >= self.consensus_threshold

        # Compute aggregate confidence
        if best_voters:
            avg_confidence = sum(v.weighted_score for v in best_voters) / len(
                best_voters
            )
        else:
            avg_confidence = 0.0

        # Override: if confidence is too low, downgrade to HOLD
        if avg_confidence < self.min_weighted_confidence:
            consensus_met = False

        final_action = best_action if consensus_met else "HOLD"

        # Merge extra data from the best voters (prefer first voter's values)
        merged_extra = {}
        for voter in best_voters:
            for k, v in voter.extra.items():
                if k not in merged_extra:
                    merged_extra[k] = v

        result = EnsembleSignal(
            action=final_action,
            confidence=avg_confidence,
            votes_for=votes_for,
            votes_total=votes_total,
            consensus_met=consensus_met,
            regime=regime_state.regime,
            strategy_votes=votes,
            extra=merged_extra,
        )

        logger.info(
            "Ensemble: %s (votes=%d/%d, conf=%.2f, regime=%s, consensus=%s)",
            final_action, votes_for, votes_total, avg_confidence,
            regime_state.regime.value,
            "✓" if consensus_met else "✗",
        )

        return result

    @staticmethod
    def _normalize_strategy_name(name: str) -> str:
        """Normalize strategy name to match affinity keys."""
        # Convert class-style names like "SqueezeBreakoutLive" to "squeeze_breakout"
        # and strip common suffixes
        import re
        # Remove "Live", "Strategy" suffixes
        cleaned = re.sub(r"(Live|Strategy|Backtest)$", "", name)
        # CamelCase to snake_case
        s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", cleaned)
        result = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()
        return result
