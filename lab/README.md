# lab/

Experiments that are not validated or have no reliable data source. **Not used by the
dashboard**: nothing in `etl/` or `spa/index.html` imports or loads them, and pytest does not
collect them. A piece comes back only with a documented definition, a test, and a valid source.

| path | what | why it is parked |
|---|---|---|
| `spa_experimental.js` | market read (`computeView`), regime scatter, volatility / gas→power β | unvalidated thresholds; residual percentile measures the daily cycle; log returns break on prices ≤ 0; peak hours in the browser's time zone |
| `residual_boundary/` | the boundary-reconciliation check behind node A, with its two figures | analysis record, not pipeline code |
| `settle_check.py` | measures ENTSO-E's real revision horizon, to tune `SETTLE_MIN` | manual tool, not run in CI |
| `scripts/` | one-off probes: frequency check, residual check, ENTSO-E timing, Yahoo probe | they call the network at import; not tests |

Run scripts from the repo root with the repo on the path, e.g.
`PYTHONPATH=. python lab/scripts/check_freq.py` or `python lab/settle_check.py`.
