# GigBid Data Card

## Purpose and scope

GigBid uses job-posting examples to exercise discovery, job analysis, risk assessment, and
market-price estimation. Portfolio and client examples support evidence retrieval and workflow
tests. Public job listings do not provide verified freelancer outcomes or proof that a freelancer
has performed the listed work.

## Data currently present

| Source | Status | Intended use | Limitations |
|---|---|---|---|
| `data/sample/jobs.json` | Synthetic starter examples | Local workflow and safety smoke tests | Two examples are not representative and are not an evaluation set. |
| `data/sample/client_history.json` | Synthetic starter example | Client-history schema and UI tests | The starter explicitly warns not to treat it as a real trust signal. |
| `data/sample/freelancers.json` | Synthetic starter example | Onboarding/profile tests | Fictional profile; not a real person's identity or qualifications. |
| `data/sample/portfolio_items.json` | Synthetic starter example | Portfolio MCP and retrieval smoke tests | The record is labelled synthetic and coursework; it is not evidence for a real proposal. |
| `data/policy_pack/marketplace_policy.md` | Instructor-provided starter policy summary | Local compliance development | Verify against the assignment and official platform rules; it is not legal advice. |
| `evals/data/synthetic_retrieval_dev.json` | Hand-authored synthetic development data, version 1.0 | Retrieval component smoke evaluation | 18 fictional items and 12 labelled queries, six items per persona; labels are not independently validated. |

The starter examples are distinguishable in their content, including the portfolio source text
`synthetic sample; replace with verified portfolio evidence`. The default Portfolio MCP data path
uses this synthetic sample only to make local development reproducible.
Portfolio evidence supports a `data_kind` field (`real`, `synthetic`, or `unverified`); legacy
sources containing the explicit word `synthetic` are marked synthetic when no label is supplied,
and all other unlabelled
evidence remains unverified. Only records explicitly marked real can support a bid-path draft.

The optional [local ingestion CLI](../rag/ingest/README.md) writes user-supplied Markdown,
text, extracted PDF text and metadata into an ignored local JSON index by default. PDF extraction
may be incomplete or reordered and must be reviewed against the original. It requires an explicit rights
attestation for records declared real. This is a user assertion, not verified evidence of
ownership, permission, accuracy, or consent; review rights and content before use. Source files,
manifest, and index can contain private text and should not be committed or deployed publicly.
No actual user portfolio is supplied or included in the repository by this feature.
The separate opt-in GitHub MCP loader reads explicitly selected files at pinned commits and
preserves GitHub links as provenance. The operator must review repository rights and content;
the link does not establish authorship or authorization, and the loader does not redact secrets.
No authenticated live GitHub ingestion has been verified.
The opt-in local SQLite document manager stores uploaded documents' extracted text and declared
metadata, but not raw uploaded files. It does not redact sensitive content, independently verify
rights, isolate tenants, or encrypt data. Deletion affects the current index, not graph checkpoints
or backups. The managed SQLite corpus is separate from manifest-generated JSON indexes.

## Candidate external datasets

The instructor provided these Kaggle dataset pages as possible sources. They are candidates, not
datasets currently included in this repository. Before downloading or using any of them, record
the dataset version, owner, exact Kaggle license/terms, retrieval date, and any restrictions in the
table below. A Kaggle URL alone does not establish a license or grant permission to redistribute
the files.

| Candidate | Potential use | Status / caveat |
|---|---|---|
| [Upwork Job Postings 2024 — 50K records](https://www.kaggle.com/datasets/asaniczka/upwork-job-postings-dataset-2024-50k-records) | Job text normalization, taxonomy, and offline retrieval experiments | Kaggle page describes data collected over two weeks. Not downloaded; license, fields, provenance, and platform-term implications not verified. |
| [All Jobs on Upwork — 200K+](https://www.kaggle.com/datasets/asaniczka/all-jobs-on-upwork-200k-plus) | Larger job-search and deduplication experiments | Kaggle page describes minute-by-minute collection. Not downloaded; provenance, duplication, license, and platform-term implications not verified. |
| [Upwork Freelance Jobs — 60K](https://www.kaggle.com/datasets/ahmedmyalo/upwork-freelance-jobs-60k) | Alternative job-posting corpus for robustness checks | Kaggle page describes jobs scraped in 2023. Not downloaded; overlap, license, provenance, and platform-term implications not verified. |
| [Freelance Contracts — 1.3M entries](https://www.kaggle.com/datasets/asaniczka/freelance-contracts-dataset-1-3-million-entries) | Price/statistics exploration if fields and rights are suitable | Kaggle page describes contracts from a freelancing website. Not downloaded; source, contract/outcome semantics, privacy, and license not verified. |
| [Freelancer Success, Earnings and Churn Prediction](https://www.kaggle.com/datasets/sarveshchhetri/freelancer-success-earnings-and-churn-prediction) | Exploratory feature/label analysis only after provenance review | Kaggle page describes 12K “real-world style” records and labels the topic synthetic. Treat labels as synthetic/unverified, not GigSim outcomes or empirical real-world facts. |
| [Trial 1](https://www.kaggle.com/datasets/adityammantri/trial-1) | Scam-risk experiments only if label definitions and rights are suitable | Kaggle page title/description identify fake-job-posting detection. Not downloaded; provenance, label construction, fields, and license not verified. |

Page titles/descriptions above were checked on 2026-11-11. The pages inspected did not establish
the data license or permission to redistribute; confirm the current dataset license and applicable
platform terms on Kaggle before acquisition or use.

Do not treat scraped or public job-posting data as authorization to scrape a live marketplace. The
live product must use the official Upwork MCP server or other approved APIs as required by the
assignment. External Kaggle corpora must not contain or be used to infer hidden test data.

## Planned selection and preprocessing

1. Inspect each candidate's Kaggle page and files; document license/terms and schema before
   acquisition. Prefer one suitable job-postings dataset for offline jobs. Do not select datasets
   whose page describes frequent scraping until rights and applicable platform terms are reviewed.
   Consider the contracts dataset for market-statistic experiments only if its source and license
   are clear.
2. Keep original downloads outside Git and preserve source/version metadata. Commit only derived,
   permitted artifacts required for reproducibility; do not redistribute source rows unless the
   license allows it.
3. Normalize column names and text encoding; retain source dataset, source row ID, retrieval date,
   and transformation version.
4. Remove exact duplicates and flag near-duplicates across sources. Do not silently combine
   datasets with different currency, time, or outcome definitions.
5. Exclude or mask direct contact details and other unnecessary personal data. Do not use
   third-party client identity/history as a trustworthy risk signal without validation.
6. Clearly separate external real-world examples, synthetic examples, and GigSim evaluation data.
   Never mix the hidden set into development, training, or committed results.
7. Keep a versioned manifest of counts before/after filtering, field mappings, dropped-row
   reasons, license, and limitations alongside each evaluation result.

## Synthetic data policy

Synthetic portfolios, clients, proposals, reviews, and conversations may be generated for local
tests when source material is unavailable. Label each record or dataset as synthetic, avoid
presenting generated outcomes as measured results, and never use synthetic records as gold labels
for the hidden evaluation.

## Known limitations and open work

- The currently available starter data is tiny and illustrative; it cannot support reliable model
  comparisons or generalizable performance claims.
- The retrieval dev labels and synthetic examples were authored for this project, not gathered or
  adjudicated independently. The simulator risk evaluation uses the simulator's generated scam
  labels. Details and commands are documented in [`evals/README.md`](../evals/README.md).
- The isolated outcome evaluation automatically confirms fictional proposals only in a fresh
  in-process simulator; its fair-price bands and reply/hire behavior are synthetic model outputs.
  These records do not represent real consent, actual freelancer experience or real client outcomes.
- No instructor GigSim package, persona corpora, or development evaluation set was found in the
  pasted starter-kit directory at the time of this update. A teaching assistant said we build the
  simulator ourselves, so `gigsim_local/` generates fully synthetic jobs (about 12% hidden-labelled
  scams), clients with hidden preferences, and a deterministic reply model from a seed. Outcomes
  measured against it must be labelled "local GigSim stand-in"; they say nothing about real
  platforms or the instructor's hidden test run.
- Kaggle dataset licenses, schemas, versions, provenance, quality, and overlap remain unverified.
- No Kaggle data has been downloaded or used in metrics; add an acquisition/processing manifest
  before using any candidate.
