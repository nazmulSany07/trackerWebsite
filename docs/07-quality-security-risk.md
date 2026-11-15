# 07. Quality, security, and risk

Draft 0.1 · 15 November 2026 · For partner review

## Correctness rules

These are not negotiable during the build. A change that breaks one does not ship.

| # | Rule |
|---|---|
| Q-01 | Money, prices, and quantities are exact decimals from the database to the screen |
| Q-02 | Every change to money, a position, a holding, or an idea writes an audit entry in the same transaction |
| Q-03 | A published idea is never changed. Trades, transactions, and cashflows are never changed or deleted |
| Q-04 | An event is published if and only if the change that caused it was saved |
| Q-05 | One alert per trigger and quote time. One delivery per alert, user, and channel |
| Q-06 | A stale or off-session quote never fires a trigger |
| Q-07 | Every alert is in the inbox before any other channel is tried |
| Q-08 | The trading rules have unit tests, and those tests gate every release |

## Proposed service targets

These numbers are proposals for the partners to confirm (open decision E-4). They are stated so that the build has something to measure against.

| Subject | Proposed target |
|---|---|
| Alert timing | An alert is handed to WhatsApp or push within one minute of its quote being stored |
| EOD import | A full-market EOD file is imported and the model book updated within five minutes |
| Page response | A normal page loads its data within two seconds on a mobile connection |
| Availability | The platform is reachable throughout DSE trading hours on trading days |
| Backup | Databases are backed up every night to a second location |
| Recovery | The platform can be restored from backup within four hours, proven by a drill before launch |

## Security

### Sign-in and sessions

- One-time codes expire within minutes, work once, and are limited per mobile number and per network address.
- Staff passwords are stored only as salted hashes. A second sign-in factor for staff is recommended before launch.
- Session tokens are kept in cookies that browser scripts cannot read and that are sent only over HTTPS. Requests that change data are protected against cross-site forgery.
- There are no default accounts, passwords, or keys in any environment. The proof of concept creates a default admin password and falls back to a fixed secret key. The platform must do neither.

### Access

- The gateway checks who is calling. Each service checks the role again for its own actions.
- Every read or change of a client book is filtered by the signed-in investor's id inside the service. Hiding a link in the web app is not access control.
- The audit log can be read by admins and changed by no one.

### Input and files

- Every request is validated on the server, whatever the web app already checked.
- Uploaded spreadsheets are limited in type and size, stored outside the database, and read as data only. Formulas and macros are ignored.
- Messages arriving from WhatsApp are accepted only when their signature is verified.

### Operations

- All public traffic uses HTTPS.
- Secrets come from the host environment, differ between staging and production, and are never committed.
- The gateway limits request rates per user and per address.
- Dependencies are scanned for known vulnerabilities in the build.
- The proof of concept lets a signed-in user download the whole database. The platform has no such feature. Backups are an operations task.

## Privacy

- A client book is visible only to its investor. Whether an investor can choose to share it with the desk is open decision B-4.
- Mobile numbers are used for sign-in and for the channels the investor has agreed to, and for nothing else.
- WhatsApp messages require recorded consent, and withdrawing consent takes effect at once.
- Logs never contain one-time codes, tokens, or holdings.
- Aggregates shown to the desk, such as how many investors bought an idea, do not identify individuals unless B-4 allows it.
- The data protection requirements that apply in Bangladesh, and the retention period for financial records, are to be confirmed with a lawyer (open decisions B-2 and B-8).

## Compliance

The platform publishes trade guidance to the public. Whether that requires a licence or registration from the Bangladesh Securities and Exchange Commission, and under what conditions it can be charged for, must be confirmed with a lawyer before launch (open decision B-2). This document does not give a legal opinion.

Whatever the answer, the platform is designed to keep the record a regulator or a dispute would ask for:

- Every idea, with its author and publication time, unaltered.
- Every update to an idea.
- Who was sent each alert, on which channel, and whether it arrived.
- What each investor reported doing.
- A disclaimer on every idea stating that it is guidance, not an order, and that the platform does not execute trades.

## Risks

| # | Risk | Effect | How we reduce it |
|---|---|---|---|
| R-01 | No licensed source of live DSE prices is secured | Alerts stay once a day, which limits the product's main promise | Version 1 is built to be useful on EOD data. The live feed is a replaceable source inside the market service. Start the licensing conversation now (D-2) |
| R-02 | Meta does not approve the WhatsApp templates, or restricts the number for low quality | WhatsApp alerts stop | Apply for business verification and templates early (D-3). Keep messages to alerts the investor asked for. The inbox and push still work |
| R-03 | Corporate actions are entered late or wrongly | Quantities, costs, and profit figures are wrong in every affected book | One person owns corporate actions (D-5). Each is applied once, logged, and shown to affected investors. Tests cover bonus, rights, and split |
| R-04 | The platform's guidance needs a licence we do not hold | Launch is delayed or the product must change | Legal review before the first investor is invited (B-2) |
| R-05 | Four services are too much for a small team to run | Slow delivery and hard-to-find faults | The service count is fixed. Request ids, structured logs, and the outbox exist from the first slice. One command starts everything locally |
| R-06 | Investors do not record their fills | Exit alerts reach few people and investor results are empty | Recording a fill takes two taps from the alert. The desk can see follow rates per idea |
| R-07 | Broker spreadsheet formats vary and change | Uploads fail and investors give up | Column mapping by hand, a preview before saving, and manual entry as a fallback |
| R-08 | One-time codes are abused to run up SMS cost | Unplanned cost and blocked sign-ins | Limits per number and per address, and an alert to the team on unusual volume |
| R-09 | The single server fails | The platform is down until restored | Nightly off-server backups, a rehearsed restore, and a review of hosting before the live feed |
| R-10 | Too many alerts | Investors mute the platform | Audience rules, quiet hours, symbol mute, and an optional daily digest |
| R-11 | A fault exposes one investor's book to another | Loss of trust and possible legal exposure | Ownership checks inside the service, a test for it (AC-15), and no holdings in logs |
| R-12 | iPhone users do not receive push | Alerts are missed | WhatsApp and the inbox cover them. The web app explains how to enable push on an iPhone |
| R-13 | The model book's published results differ from what a follower could achieve | Loss of trust | Record results from publication time, include charges (T-3), and settle the fill-price rules (T-1, T-2) before launch |
| R-14 | The EOD file arrives late or malformed | No alerts that day | Clear import errors, column mapping, and a team alert if no file is imported by an agreed time (D-1) |
