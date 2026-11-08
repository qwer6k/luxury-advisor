# XUYU · Client Advisor Studio

Prepared by **liukai**. A local luxury client-advisor drafting tool with six communication scenarios, evidence-based client profiles and four switchable visual themes. The brand, products and example clients are fictional.

## What to review

- [Application backend](src/luxury_advisor) — shared drafting, client memory, limited rewriting and rule checks.
- [React frontend](web/src) — workbench, client profiles, product context and visual themes.
- [Architecture](docs/Architecture.svg).
- [Brand and fact assumptions](docs/Brand_Assumptions.md).
- [Campaign protocol](docs/Campaign_Protocol.md).
- [Historical source snapshots](baselines) — private calibration data and review-provenance tests are deliberately omitted.

The English report, evaluation workbook, actual generation records, human review notes and timestamped Codex conversation evidence are supplied **privately with the submission email**. They are not published in this repository. API credentials, the working customer database and the original challenge brief are excluded.

## Run locally

Install Python 3.11+ and [uv](https://docs.astral.sh/uv/). The frontend is already built; Node is not needed to run the local demo.

```sh
git clone https://github.com/qwer6k/luxury-advisor.git
cd luxury-advisor
./start.sh
```

Open http://127.0.0.1:8002 . The default mode makes no model calls. It provides the workbench, theme switching and freshly seeded fictional client profiles. Existing generations and review records are absent until you extract the private email evidence into this directory. The review entry appears when its private dataset is installed.

For live drafting, copy `.env.example` to `.env`, supply your own DeepSeek API key and run:

```sh
LUXURY_DEMO_READONLY=0 ./start.sh
```

Keep `.env` local. The application is intended for localhost and does not automatically send messages to customers.

## Private evidence overlay and version scope

The separately emailed `Evidence.zip` is extracted **inside this repository directory**. It restores private calibration examples, original review datasets, actual saved runs and structured evaluations to their original relative paths. The original calibration file replaces the public rules-only configuration. Do not commit the private overlay: `.gitignore` blocks its record directories, and `data/reply_calibration.json` will contain private records after extraction.

The public rules-only configuration contains no original review labels or example messages and has no human-approved example coverage. Its live wording can therefore differ from the frozen formal campaign. The drafting engine is unchanged; the public edition also makes the review entry conditional on private dataset availability. Historical source snapshots omit the same private material. Formal findings belong to the frozen versions identified in the private report, not to a fresh public-edition model run.

The complete original local submission bundle is retained by the author. No claim is made that a new run will reproduce stochastic model output byte for byte.

## Offline engineering checks

```sh
uv sync --frozen
uv run --no-sync python -m unittest discover -s tests -v
uv run --no-sync luxury-advisor --cases-file data/formal_cases.json
```

These use offline test doubles and input validation, not paid model calls. The public test suite excludes six checks tied to withheld human-review provenance. It discovers 77 tests: 71 run without private data, while six regressions against actual saved outputs are explicitly skipped until the private evidence overlay is installed. The original 83-check engineering result is documented in the private evidence. Evaluation inputs are fictional; generated candidates and actual judgments remain private.

For frontend development or rebuilding:

```sh
cd web
npm ci
npm run build
```

The R1 campaign has 50 cases and 150 actual candidates. R2 is a selected nine-case retest. Human review covers a 36-candidate sample, with the remaining 114 unreviewed. These results, remaining defects and evaluator limitations are reported separately in the emailed report and workbook. This work does not establish real customer emotion or sales conversion.
