"""Tests for pure/static methods in BinanceExchange (no HTTP mocking needed)."""

import logging
import time

import pytest

from integrations.exchanges.binance import BinanceExchange


# ----------------------------------------------------------------
# _to_binance_symbol
# ----------------------------------------------------------------

class TestToBinanceSymbol:
    def test_standard_pair(self):
        assert BinanceExchange._to_binance_symbol("BTC/USDT") == "BTCUSDT"

    def test_already_flat(self):
        assert BinanceExchange._to_binance_symbol("BTCUSDT") == "BTCUSDT"

    def test_three_letter_quote(self):
        assert BinanceExchange._to_binance_symbol("ETH/AUD") == "ETHAUD"

    def test_stablecoin_pair(self):
        assert BinanceExchange._to_binance_symbol("USDC/USDT") == "USDCUSDT"


# ----------------------------------------------------------------
# _to_standard_pair
# ----------------------------------------------------------------

class TestToStandardPair:
    def test_known_quote(self):
        assert BinanceExchange._to_standard_pair("BTCUSDT", "USDT") == "BTC/USDT"

    def test_non_matching_quote(self):
        assert BinanceExchange._to_standard_pair("BTCAUD", "USDT") == "BTCAUD"

    def test_custom_quote(self):
        assert BinanceExchange._to_standard_pair("ETHAUD", "AUD") == "ETH/AUD"

    def test_default_quote(self):
        assert BinanceExchange._to_standard_pair("SOLUSDT") == "SOL/USDT"


# ----------------------------------------------------------------
# _map_interval
# ----------------------------------------------------------------

class TestMapInterval:
    @pytest.mark.parametrize("minutes,expected", [
        (1, "1m"), (5, "5m"), (15, "15m"), (30, "30m"),
        (60, "1h"), (240, "4h"), (1440, "1d"), (10080, "1w"),
    ])
    def test_all_valid_intervals(self, binance_prod, minutes, expected):
        assert binance_prod._map_interval(minutes) == expected

    def test_invalid_interval(self, binance_prod):
        with pytest.raises(ValueError, match="Unsupported interval 3m"):
            binance_prod._map_interval(3)

    def test_zero_interval(self, binance_prod):
        with pytest.raises(ValueError, match="Unsupported interval 0m"):
            binance_prod._map_interval(0)


# ----------------------------------------------------------------
# _round_step
# ----------------------------------------------------------------

class TestRoundStep:
    def test_round_down_lot_size(self):
        assert BinanceExchange._round_step(1.23456789, 0.001) == 1.234

    def test_round_down_btc_step(self):
        assert BinanceExchange._round_step(0.00015678, 0.00001) == 0.00015

    def test_step_one(self):
        assert BinanceExchange._round_step(123.456, 1) == 123.0

    def test_step_zero(self):
        assert BinanceExchange._round_step(123.456, 0) == 123.456

    def test_step_negative(self):
        assert BinanceExchange._round_step(123.456, -1) == 123.456

    def test_very_small_step(self):
        assert BinanceExchange._round_step(0.12345678, 0.00000001) == 0.12345678

    def test_exact_multiple(self):
        assert BinanceExchange._round_step(0.003, 0.001) == 0.003

    def test_rounds_down_not_up(self):
        assert BinanceExchange._round_step(0.00999, 0.001) == 0.009


# ----------------------------------------------------------------
# _normalise_order
# ----------------------------------------------------------------

class TestNormaliseOrder:
    def test_filled_market_order(self):
        raw = {
            "orderId": 123456,
            "executedQty": "0.01000000",
            "cummulativeQuoteQty": "654.32",
            "status": "FILLED",
            "origQty": "0.01000000",
        }
        result = BinanceExchange._normalise_order(raw, "BTC/USDT", "buy")
        assert result["order_id"] == "123456"
        assert result["txid"] == ["123456"]
        assert result["status"] == "FILLED"
        assert result["price"] == pytest.approx(65432.0)
        assert result["filled_base"] == 0.01
        assert result["filled_quote"] == 654.32
        assert result["pair"] == "BTC/USDT"
        assert result["side"] == "buy"
        assert result["volume"] == 0.01
        assert result["cost"] == 654.32

    def test_zero_executed_qty(self):
        raw = {
            "orderId": 789,
            "executedQty": "0.00000000",
            "cummulativeQuoteQty": "0.00000000",
            "status": "NEW",
            "origQty": "0.01000000",
        }
        result = BinanceExchange._normalise_order(raw, "BTC/USDT", "buy")
        assert result["price"] == 0.0  # no division by zero

    def test_partial_fill(self):
        raw = {
            "orderId": 456,
            "executedQty": "0.00500000",
            "cummulativeQuoteQty": "327.16",
            "status": "PARTIALLY_FILLED",
            "origQty": "0.01000000",
        }
        result = BinanceExchange._normalise_order(raw, "BTC/USDT", "buy")
        assert result["filled_base"] == 0.005
        assert result["volume"] == 0.01


# ----------------------------------------------------------------
# URL selection
# ----------------------------------------------------------------

class TestUrlSelection:
    def test_production_url(self):
        ex = BinanceExchange(api_key="k", api_secret="s", testnet=False)
        assert ex.base_url == "https://api.binance.com"

    def test_testnet_url(self):
        ex = BinanceExchange(api_key="k", api_secret="s", testnet=True)
        assert ex.base_url == "https://testnet.binance.vision"

    def test_env_var_true(self, monkeypatch):
        monkeypatch.setenv("BINANCE_TESTNET", "true")
        monkeypatch.setenv("BINANCE_API_KEY", "k")
        monkeypatch.setenv("BINANCE_API_SECRET", "s")
        ex = BinanceExchange()
        assert ex.base_url == BinanceExchange.TESTNET_URL

    def test_env_var_yes(self, monkeypatch):
        monkeypatch.setenv("BINANCE_TESTNET", "yes")
        monkeypatch.setenv("BINANCE_API_KEY", "k")
        monkeypatch.setenv("BINANCE_API_SECRET", "s")
        ex = BinanceExchange()
        assert ex.base_url == BinanceExchange.TESTNET_URL

    def test_env_var_false(self, monkeypatch):
        monkeypatch.setenv("BINANCE_TESTNET", "false")
        monkeypatch.setenv("BINANCE_API_KEY", "k")
        monkeypatch.setenv("BINANCE_API_SECRET", "s")
        ex = BinanceExchange()
        assert ex.base_url == BinanceExchange.BASE_URL

    def test_constructor_overrides_env(self, monkeypatch):
        monkeypatch.setenv("BINANCE_TESTNET", "true")
        ex = BinanceExchange(api_key="k", api_secret="s", testnet=False)
        assert ex.base_url == BinanceExchange.BASE_URL


# ----------------------------------------------------------------
# Credential loading
# ----------------------------------------------------------------

class TestCredentialLoading:
    def test_explicit_keys(self, monkeypatch):
        monkeypatch.setenv("BINANCE_API_KEY", "env_key")
        ex = BinanceExchange(api_key="explicit_key", api_secret="s", testnet=False)
        assert ex.api_key == "explicit_key"

    def test_env_fallback(self, monkeypatch):
        monkeypatch.setenv("BINANCE_API_KEY", "env_key")
        monkeypatch.setenv("BINANCE_API_SECRET", "env_secret")
        ex = BinanceExchange(testnet=False)
        assert ex.api_key == "env_key"
        assert ex.api_secret == "env_secret"

    def test_no_keys_warning(self, caplog):
        with caplog.at_level(logging.WARNING):
            BinanceExchange(api_key="", api_secret="", testnet=False)
        assert "Binance API credentials not configured" in caplog.text


# ----------------------------------------------------------------
# Name property
# ----------------------------------------------------------------

class TestName:
    def test_name(self, binance_prod):
        assert binance_prod.name == "binance"


# ----------------------------------------------------------------
# Rate limit tracking
# ----------------------------------------------------------------

class TestRateLimitTracking:
    def test_weight_recorded(self, binance_prod):
        binance_prod._record_weight(10)
        assert len(binance_prod._request_log) == 1

    def test_old_entries_pruned(self, binance_prod, monkeypatch):
        # Insert an entry 61 seconds ago
        old_time = time.time() - 61
        binance_prod._request_log.append((old_time, 100))
        # Record a new entry; the old one should be pruned
        binance_prod._record_weight(1)
        assert len(binance_prod._request_log) == 1

    def test_warning_at_80pct(self, binance_prod, caplog):
        with caplog.at_level(logging.WARNING):
            # 961 weight > 1200 * 0.8 = 960
            binance_prod._record_weight(961)
        assert "rate limit approaching" in caplog.text.lower()

    def test_no_warning_below_threshold(self, binance_prod, caplog):
        with caplog.at_level(logging.WARNING):
            binance_prod._record_weight(100)
        assert "rate limit" not in caplog.text.lower()
