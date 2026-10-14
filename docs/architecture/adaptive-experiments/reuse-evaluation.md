# External patterns to evaluate, not blanket dependencies

## Rule

Preserve Drift's existing scientific and accounting contracts. A popular project
is a source of implementation patterns, not proof of financial performance or
permission to copy data/model weights. Record upstream commit/version, exact
files, license/NOTICE obligations, dependencies, compatibility, security and
acceptance tests before any future code reuse. The coordination bootstrap
installs and vendors nothing.

## Candidate references

| Reference | Relevant contribution | Drift action | Not adopted automatically |
|---|---|---|---|
| Microsoft RD-Agent / R&D-Agent-Quant | Separates research proposals, development, execution and feedback; studies adaptive research scheduling. | Apply clear task specifications, failure feedback and bounded research budgets in existing M6-M8. | Whole agent runtime, unbounded code generation or bandit scheduling in the bounded MVP. |
| Microsoft Qlib | Experiment/run recording and modular quantitative research workflows. | Use explicit campaign/run/record identities and reproducible artifact references in Drift's existing ledger. | A second backtester, separate authoritative experiment database or automatic MLflow migration. |
| AI4Finance FinGPT | Financial sentiment, extraction and retrieval-augmented text analysis with task benchmarks. | Evaluate NLP adapters and labeled fixtures for Krish's significance layer. | Claims that sentiment accuracy implies profit, an entire model stack or source scrapers. |
| AI4Finance FinNLP | Provider-specific data-adapter examples. | Reference normalization patterns only after access and security review. | Old scraping code, embedded credentials, assumed lawful access or absence of data treated as neutral news. |
| QuantConnect LEAN framework | Distinct signal, portfolio construction, risk and execution responsibilities. | Preserve modular intent/risk/execution separation and explicit scheduling in Drift. | Replacement of the M2 accounting engine or inference that its fills match our data. |
| Backtest-overfitting literature | Selection bias from repeated trials; DSR/PBO methods with statistical assumptions. | Preregister comparisons, log all attempts, preserve confirmation data and report uncertainty. | A universal numerical pass threshold or a claim that one statistic proves an edge. |

The open-source licenses reported by RD-Agent/Qlib/FinGPT/FinNLP are MIT and
LEAN is Apache-2.0. Verify the exact reused revision and separate model/data
terms before implementation. Do not treat README benchmark claims as replicated
Drift evidence. No star-count, return, speed or cost claim is necessary to justify
these design boundaries.

## Sources

- RD-Agent: https://github.com/microsoft/RD-Agent
- R&D-Agent-Quant: https://arxiv.org/abs/2505.15155
- Qlib: https://github.com/microsoft/qlib
- Qlib experiment recorder: https://qlib.readthedocs.io/en/stable/component/recorder.html
- FinGPT: https://github.com/AI4Finance-Foundation/FinGPT
- FinGPT retrieval paper: https://arxiv.org/abs/2310.04027
- FinNLP: https://github.com/AI4Finance-Foundation/FinNLP
- LEAN: https://github.com/QuantConnect/Lean
- LEAN framework: https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview
- The Deflated Sharpe Ratio: https://doi.org/10.3905/jpm.2014.40.5.094
- The Probability of Backtest Overfitting: https://escholarship.org/uc/item/4w1110bb
- GitHub issue dependencies: https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/creating-issue-dependencies
- GitHub code owners: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners
- Cursor rules: https://cursor.com/docs/rules

## Coordination implications

GitHub dependencies represent blockers, not task ownership locks or an agent
scheduler. Closing a dependency does not automatically validate contracts or
correct state labels. CODEOWNERS routes review; it does not lock files and does
not automatically request reviews on draft PRs. Cursor rules and AGENTS.md guide
agents; they are not an enforcement boundary. Keep critical rules in tests,
review and permissions as well as prose. Do not deploy new automation in the
bootstrap merely to suggest that idle agents can wake themselves.
