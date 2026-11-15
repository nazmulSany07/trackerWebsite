# Platform documentation

Draft 0.1 · 15 November 2026 · For partner review

This folder is the planning baseline for the new DSE investor platform. It describes what we intend to build, for whom, and how. Nothing in it is built yet. The only existing code is the proof of concept in `app.py`, a single-user Flask tracker whose trading rules we are carrying forward.

The working title is not decided. These documents call it "the platform".

## Read in this order

| # | Document | What it answers |
|---|---|---|
| 01 | [Product brief](01-product-brief.md) | What the platform is, who it is for, what is in version 1 |
| 02 | [Glossary](02-glossary.md) | The one meaning of each word we use |
| 03 | [Users and journeys](03-users-and-journeys.md) | Roles, permissions, user flow diagrams, acceptance checks |
| 04 | [Architecture](04-architecture.md) | Services, how they talk, technology stack, environments |
| 05 | [Data model](05-data-model.md) | What each service stores and how the records relate |
| 06 | [Decision log](06-decision-log.md) | Choices already made and why |
| 07 | [Quality, security, and risk](07-quality-security-risk.md) | Rules the build must meet, and what could go wrong |
| 08 | [Delivery plan](08-delivery-plan.md) | Build order, team, definition of done, testing |
| 09 | [Screen map](09-screen-map.md) | Every version 1 screen and who sees it |
| 10 | [Open decisions](10-open-decisions.md) | Questions the partners must answer before or during the build |

A partner who has ten minutes should read 01, the diagrams in 03, and 10.

## What is settled and what is not

Settled: the product shape, the four backend services, the technology stack, and the build order. These are recorded in the decision log.

Not settled: the business model, the legal position, the data source for live prices, and a number of trading-rule details. These are listed in [Open decisions](10-open-decisions.md). Several of them block specific build slices, and the table there says which.

This baseline contains no dates, cost estimates, or team size. Those belong in the partners' plan, and they depend on answers to the open decisions.

## Viewing the diagrams

The diagrams are written in Mermaid inside the Markdown files. They render on GitHub and GitLab, and in the Markdown preview of Cursor and VS Code. In a plain text viewer they appear as code.

## Keeping this current

These files live in the repository and change through review, like code. A document is updated in the same change that makes it wrong. Detailed API specifications and the operations runbook are not here: the API specification is generated from the services once endpoints exist, and the runbook is written when a staging environment exists to fail.
