# Exact comparisons at hard exposure caps

Issue [#641](https://github.com/KanujVerma/drift/issues/641) corrects fractional
basis-point gaps in the existing M13 single-position and gross-exposure maxima.
It builds on [#640](https://github.com/KanujVerma/drift/pull/640)'s cached-approval
emergency-stop correction, without modifying that branch.

## Reproduced behavior

The gatekeeper converted projected exposure to an integer number of basis points
before comparing it with the maximum. For a synthetic NAV of 10000, it allowed a
position worth 2500.50 against a 2500-bps limit, or gross holdings worth 5000.50
against a 5000-bps limit. Both exceed the configured maximum. A zero cap even
allowed positive exposure worth 0.50. These actual offline verdicts contradict
the existing strict-cap requirement; no new risk policy is needed.

Removing the integer conversion alone is insufficient at the Decimal precision
boundary. With NAV `9999.999999999999999999999999999999`, notional `3333` and cap
`3333`, the rounded 34-digit division produces a ratio equal to the cap, although
the represented amounts place the order strictly above it.

## Comparison rule

For positive NAV, compare these two products directly:

```text
projected_notional * 10000 > NAV * configured_cap_basis_points
```

Canonical monetary inputs and the existing monetary projections have at most
34 significant digits. Both integer factors have at most five digits under the
unchanged V1 policy constraints. A nested comparison context adds exactly five
guard digits, enough to preserve both products without ratio division or integer
truncation. It inherits the pinned context's other settings and restores the
caller's context on exit. It returns only a Boolean; it does not create a wider
stored amount or change the portfolio arithmetic contract. Arithmetic errors
propagate rather than granting permission.

Equal and below-limit amounts retain their existing behavior. Any represented
excess is rejected, including a fractional basis point and positive exposure
under a zero maximum. The same rule includes already-held positions and gross
holdings. Rejection reasons retain their existing category prefixes and name the
projected notional, NAV and cap, avoiding a misleading rounded inequality.

This change does not alter configured limits, quantity/notional checks, drawdown
thresholds, SELL handling, rate limits, caches, journal schemas or historical
verdicts. It compares the existing projected monetary values; it does not redesign
their calculation or supply missing portfolio state to callers that omit it.

## Verification

Against unchanged parent `a786960e526b37c03abb5315a9975d5da0056053`, the new suite
produced 50 behavioral failures and 24 passing controls. Its 74 cases cover both
caps, zero and nonzero limits, below/equal/above boundaries, existing holdings,
the 34-digit division case and three caller Decimal contexts. The boundary table
uses independent exact `Fraction` comparisons as its oracle.

```text
uv run --locked pytest tests/unit/test_risk_exposure_boundaries.py
```

The issue and PR record consumer/adversarial regressions, lint/type/build checks
and full canonical CI for the published head. These fixture tests establish
bounded arithmetic behavior, not operational trading permission or economic
research qualification.
