from datetime import date, timedelta

import numpy as np
import pandas as pd

from toolkit.models import Position
from toolkit.portfolio import value_portfolio
from toolkit.pricing import black_scholes, implied_volatility
from toolkit.risk import var_es
from toolkit.storage import Repository
from toolkit.strategy import demo_chain, rank_option_chain, strategy_distribution
from toolkit.volatility import ewma_volatility, historical_volatility


def test_put_call_parity_and_greeks():
    s,k,t,r,q,v=100,105,0.5,0.04,0.01,0.25
    call=black_scholes(s,k,t,r,v,"call",q)
    put=black_scholes(s,k,t,r,v,"put",q)
    assert abs((call.price-put.price)-(s*np.exp(-q*t)-k*np.exp(-r*t))) < 1e-9
    assert 0 < call.delta < 1
    assert put.delta < 0
    assert call.gamma > 0 and call.vega > 0


def test_implied_vol_round_trip():
    price=black_scholes(100,90,0.25,0.03,0.32,"call").price
    assert abs(implied_volatility(price,100,90,0.25,0.03,"call")-.32) < 1e-7


def test_portfolio_multiplier_and_signs():
    p=Position("TEST", "option", 2, 5, option_type="call", strike=100,
               expiry=date.today()+timedelta(days=90), implied_vol=.25,
               underlying_price=105, multiplier=100)
    summary, details=value_portfolio([p])
    assert summary["market_value"] == details[0]["unit_price"]*200
    assert summary["delta"] > 0 and summary["gamma"] > 0


def test_var_es_ordering():
    m=var_es(np.array([-100,-20,-10,0,5,10,20]),.80)
    assert m["es"] >= m["var"] >= 0


def test_storage_roundtrip(tmp_path):
    repo=Repository(tmp_path/"book.db")
    pid=repo.create_portfolio("test")
    repo.add_position(pid,Position("US.AAPL","equity",10,100,current_price=110))
    assert len(repo.positions(pid)) == 1
    assert repo.positions(pid).iloc[0].symbol == "US.AAPL"


def test_volatility_and_ranking():
    rng=np.random.default_rng(1)
    prices=pd.Series(100*np.exp(np.cumsum(rng.normal(0,.01,200))))
    assert historical_volatility(prices,30) > 0
    assert ewma_volatility(prices) > 0
    ranked=rank_option_chain(demo_chain(100,.25),100,.10,20,.28)
    assert len(ranked) > 10 and ranked.score.is_monotonic_decreasing


def test_strategy_distribution_is_deterministic():
    legs=pd.DataFrame([{"instrument_type":"option","option_type":"call","strike":100,
                        "quantity":1,"entry_price":8,"multiplier":100}])
    _,a=strategy_distribution(legs,100,.25,.05,.25,2000,seed=2)
    _,b=strategy_distribution(legs,100,.25,.05,.25,2000,seed=2)
    assert a == b and 0 <= a["probability_profit"] <= 1

