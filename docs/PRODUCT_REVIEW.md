# Trader Review and Product Critique

## Test performed

The running app was used as a trader would use it: inspect the market overview,
open the chain, select a call, add it to the trade builder, inspect the estimated
entry, compare vendor and model values, and review the dynamic risk controls.

The first attempt exposed an important usability flaw: the contract selector
defaulted to the lowest strike, so a 14-DTE, near-one-delta deep-ITM call was added
instead of a representative liquid contract. Phase 1 now defaults to the option
nearest 50 delta. A later chain grid should support direct row selection and
center itself around ATM.

## What is already useful

- Provider provenance and current-vs-model separation are clear.
- Exact monetary formatting makes premium and risk legible.
- Natural, conservative and midpoint entry conventions prevent accidental
  perfect-midpoint backtests.
- Full repricing makes gamma and time decay more informative than an expiry-only
  payoff diagram.
- Missing fields and indicative data remain visible.
- The generic leg model handles arbitrary same-underlying combinations.

## Critical gaps before using it for a real order

1. **The free Alpaca options feed is not executable OPRA.** Indicative values must
   never drive limit prices or transaction-cost estimates. Use paid OPRA or
   compare against the broker order ticket.
2. **No volatility surface yet.** Flat-IV Black–Scholes shocks cannot represent
   skew roll-down, sticky delta, event term structure or local smile dislocations.
3. **No American/dividend engine.** Early exercise, discrete ex-dividends and
   borrow are material for deep-ITM options.
4. **No combo market.** Leg-by-leg natural prices are deliberately conservative,
   but actual multi-leg orders trade as a net package. Capture combo bid/ask and
   fill history when the provider exposes them.
5. **No event context.** Earnings, dividends, economic releases, halts and
   corporate actions should be visible before a trade is evaluated.
6. **No order/position reconciliation.** Portfolio records are manual and can
   drift from the broker.

## Quant gaps, in priority order

### P0 — prevent misleading outputs

- Prominent delayed/indicative/stale badges and quote-age clock.
- Hard arbitrage checks: intrinsic bounds, call monotonicity/convexity,
  put-call parity, calendar sanity and vertical bounds.
- Disable “expected fill” claims when the feed is indicative.
- Expiry lifecycle handling for calendars and diagonals. Their max profit/loss
  is path-dependent; the UI now stops presenting a false single-expiry number.
- Scenario horizons cannot extend beyond the earliest leg without modeling
  settlement/reinvestment; the UI now clips them.

### P1 — make a trade decision

- Per-expiry quality-weighted spline surface and IV residual uncertainty.
- ATM term structure, 25-delta risk reversal, butterfly and forward variance.
- Realized-vol forecasts, event-vol decomposition and IV-minus-forecast premium.
- Real-world expected P&L under explicit drift/realized-vol/IV assumptions,
  alongside a separately labeled risk-neutral distribution.
- Probability of profit, touch, target and stop using Monte Carlo or empirical
  paths—not delta relabeled as probability.
- Portfolio marginal Greeks, scenario loss, concentration and liquidity cost.

### P2 — improve execution and learning

- Direct chain row-to-leg interaction and strategy presets.
- Quote sizes, NBBO/venue, quote conditions, spread percentile and quote age.
- Limit-price ladder, round-trip spread cost, fee schedule and combo fills.
- Broker position/fill synchronization and a trade journal that freezes the
  signal, surface, assumptions and data version at decision time.
- Outcome attribution by signal, IV residual, DTE, delta, event state and regime.

## Practical trader workflow after Phase 2

1. Start from an underlying thesis and holding period, not from a contract.
2. Check event calendar, liquidity and surface quality.
3. Compare single options and defined-risk structures under the same subjective
   distribution and execution assumptions.
4. Inspect scenario P&L and Greek migration at the portfolio level.
5. Size on contractual maximum loss plus realistic gap/assignment risk.
6. Record the decision state, execute with a limit, and reconcile the fill.
7. Review realized outcome against expected spot, vol, skew, time and execution
   contributions.

