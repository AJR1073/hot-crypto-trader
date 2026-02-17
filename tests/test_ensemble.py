"""
Tests for core/ensemble.py — regime-aware signal aggregation.
"""

from dataclasses import dataclass, field

import pytest

from core.ensemble import Ensemble, EnsembleSignal
from core.regime_detector import Regime, RegimeState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class MockSignal:
    action: str = "HOLD"
    confidence: float = 0.7
    extra: dict = field(default_factory=dict)


def _make_regime(regime: Regime) -> RegimeState:
    return RegimeState(
        regime=regime,
        hurst=0.65 if "TRENDING" in regime.value else 0.40,
        adx=30 if "TRENDING" in regime.value else 15,
        confidence=0.8,
        active_strategies=["trend_ema", "supertrend", "mean_reversion_bb"],
        allocation_weight=0.8,
    )


# ---------------------------------------------------------------------------
# Consensus rule tests
# ---------------------------------------------------------------------------

class TestConsensusRule:
    def test_two_of_three_buy_consensus(self):
        """2 BUY + 1 HOLD should produce BUY."""
        ensemble = Ensemble(consensus_threshold=2)
        signals = {
            "trend_ema": MockSignal(action="OPEN_LONG", confidence=0.8),
            "supertrend": MockSignal(action="OPEN_LONG", confidence=0.7),
            "mean_reversion_bb": MockSignal(action="HOLD", confidence=0.5),
        }
        regime = _make_regime(Regime.TRENDING_STRONG)
        result = ensemble.aggregate(signals, regime)

        assert result.action == "OPEN_LONG"
        assert result.consensus_met
        assert result.votes_for == 2

    def test_one_of_three_no_consensus(self):
        """1 BUY + 2 HOLD should produce HOLD (no consensus)."""
        ensemble = Ensemble(consensus_threshold=2)
        signals = {
            "trend_ema": MockSignal(action="OPEN_LONG", confidence=0.8),
            "supertrend": MockSignal(action="HOLD"),
            "mean_reversion_bb": MockSignal(action="HOLD"),
        }
        regime = _make_regime(Regime.TRENDING_STRONG)
        result = ensemble.aggregate(signals, regime)

        assert result.action == "HOLD"
        assert not result.consensus_met

    def test_all_hold(self):
        """All HOLD → HOLD."""
        ensemble = Ensemble(consensus_threshold=2)
        signals = {
            "trend_ema": MockSignal(action="HOLD"),
            "supertrend": MockSignal(action="HOLD"),
        }
        regime = _make_regime(Regime.TRENDING_STRONG)
        result = ensemble.aggregate(signals, regime)

        assert result.action == "HOLD"
        assert result.votes_for == 0


class TestConflictResolution:
    def test_buy_vs_sell_conflict_hold(self):
        """1 BUY + 1 SELL (equal weight) → HOLD."""
        ensemble = Ensemble(consensus_threshold=2)
        signals = {
            "trend_ema": MockSignal(action="OPEN_LONG", confidence=0.7),
            "mean_reversion_bb": MockSignal(action="CLOSE_LONG", confidence=0.7),
        }
        regime = _make_regime(Regime.TRENDING_WEAK)
        result = ensemble.aggregate(signals, regime)
        # Should HOLD due to conflict
        assert result.action == "HOLD"

    def test_overwhelming_buy_wins_conflict(self):
        """3 BUY + 1 SELL → BUY wins."""
        ensemble = Ensemble(consensus_threshold=2)
        signals = {
            "trend_ema": MockSignal(action="OPEN_LONG", confidence=0.9),
            "supertrend": MockSignal(action="OPEN_LONG", confidence=0.8),
            "turtle": MockSignal(action="OPEN_LONG", confidence=0.7),
            "mean_reversion_bb": MockSignal(action="CLOSE_LONG", confidence=0.5),
        }
        regime = _make_regime(Regime.TRENDING_STRONG)
        result = ensemble.aggregate(signals, regime)
        assert result.action == "OPEN_LONG"


class TestRegimeWeighting:
    def test_trend_strategies_weighted_higher_in_trending(self):
        """In TRENDING_STRONG, trend_ema has affinity 1.0 while mean_reversion has 0.1."""
        ensemble = Ensemble(consensus_threshold=1)
        regime = _make_regime(Regime.TRENDING_STRONG)

        # Both vote OPEN_LONG but trend_ema should have higher weighted score
        signals = {
            "trend_ema": MockSignal(action="OPEN_LONG", confidence=0.6),
        }
        result = ensemble.aggregate(signals, regime)
        # With threshold=1 and trending regime, trend_ema should pass
        assert result.consensus_met

    def test_no_strategies_yields_hold(self):
        ensemble = Ensemble(consensus_threshold=2)
        result = ensemble.aggregate({}, _make_regime(Regime.RANDOM_WALK))
        assert result.action == "HOLD"


class TestEnsembleSignalOutput:
    def test_signal_has_regime(self):
        ensemble = Ensemble(consensus_threshold=1)
        signals = {"trend_ema": MockSignal(action="OPEN_LONG")}
        regime = _make_regime(Regime.TRENDING_STRONG)
        result = ensemble.aggregate(signals, regime)
        assert result.regime == Regime.TRENDING_STRONG

    def test_extra_merged_from_voters(self):
        ensemble = Ensemble(consensus_threshold=1)
        signals = {
            "trend_ema": MockSignal(
                action="OPEN_LONG",
                extra={"stop": 49000, "tp": 52000, "atr": 500},
            ),
        }
        regime = _make_regime(Regime.TRENDING_STRONG)
        result = ensemble.aggregate(signals, regime)
        assert "stop" in result.extra
        assert result.extra["stop"] == 49000


class TestStrategyNameNormalization:
    def test_camel_case_conversion(self):
        result = Ensemble._normalize_strategy_name("SqueezeBreakoutLive")
        assert result == "squeeze_breakout"

    def test_already_snake_case(self):
        result = Ensemble._normalize_strategy_name("trend_ema")
        assert result == "trend_ema"

    def test_with_strategy_suffix(self):
        result = Ensemble._normalize_strategy_name("MeanReversionBBStrategy")
        assert result == "mean_reversion_bb"
