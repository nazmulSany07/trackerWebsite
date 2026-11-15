# 02. Glossary

Draft 0.1 · 15 November 2026 · For partner review

Each word has one meaning. The Java code, the TypeScript code, the screens, and these documents all use it the same way. The last column shows what the proof of concept called the same thing.

## People

| Term | Meaning |
|---|---|
| Investor | A registered user who follows ideas, keeps a client book, or both |
| Analyst | A desk member who writes and publishes ideas |
| Admin | A desk member with full access, including users, market data, and capital |
| Desk | Admins and analysts together |

## Ideas and books

| Term | Meaning | In the proof of concept |
|---|---|---|
| Idea | A trade recommendation published by the desk: symbol, trading date, buy price, required volume, target, stop, suggested quantity, and a written reason | Watchlist entry |
| Idea update | A dated note added to a published idea, such as a moved stop. The original idea is never changed | None |
| Model book | The desk's portfolio, produced by applying every idea by the fixed rules | The whole tracker |
| Position | One stock held in the model book, opened by an idea | Position |
| Model trade | A closed or partly closed position, with its profit or loss | Trade |
| Signal | A BUY or SELL that the rules produced in the model book on a given day | Signal |
| Client book | One investor's own portfolio on the platform | None |
| Holding | One stock in a client book, with quantity and average cost | None |
| Transaction | One dated change to a client book: buy, sell, bonus, rights, or split | None |
| Cashflow | A deposit or withdrawal recorded in a book | Cashflow |
| Available cash | Deposits minus withdrawals minus the cost of open holdings plus realised profit | Available |
| Equity | Available cash plus the market value of open holdings | Equity |
| Charges | Brokerage commission and other fees on a trade | Charges |

## Following

| Term | Meaning |
|---|---|
| Follow | One investor's record against one idea. Its state is Following, Bought, Partial, Skipped, or Exited |
| Following | The investor is watching the idea and has not acted |
| Bought | The investor reported buying |
| Partial | The investor reported selling part of what they bought |
| Skipped | The investor decided not to take the idea |
| Exited | The investor reported selling everything |
| Fill | A buy or sell the investor reports against an idea, with their own date, price, and quantity. A fill is stored as a transaction in the client book |
| Overlap | The comparison of a client book with the model book |

## Market data

| Term | Meaning | In the proof of concept |
|---|---|---|
| Symbol | A DSE trading code, such as GP | Symbol |
| Quote | The price and volume of a symbol at a point in time | EOD row |
| EOD quote | The open, high, low, close, and volume for one symbol on one trading day | EOD data |
| EOD import | One uploaded end-of-day file and the record of how it was processed | EOD upload |
| Live quote | A quote received during the trading session. Not available in version 1 | None |
| Stale quote | A quote older than the session clock allows. A stale quote never fires a trigger | None |
| Session clock | The trading calendar and hours, kept in Dhaka time, including holidays | Friday and Saturday closed |
| Corporate action | A bonus issue, rights issue, or split that changes quantity and cost | None |

## Alerts

| Term | Meaning | In the proof of concept |
|---|---|---|
| Trigger | A condition on a quote, owned by the desk or by an investor | Fixed buy and sell rules |
| Alert | The message produced when a trigger fires or an idea changes | Telegram message |
| Channel | In-app inbox, WhatsApp, or phone push | Telegram |
| Delivery | One attempt to send one alert to one user on one channel, with its outcome | None |
| Inbox | The in-app list of a user's alerts. It is the record even when another channel fails | None |
| Consent | An investor's recorded agreement to receive WhatsApp messages | None |
| Quiet hours | A period in which a user receives no WhatsApp or push. Alerts still reach the inbox | None |

## Engineering

| Term | Meaning |
|---|---|
| Service | One of the four backend applications: identity, market, trading, alerts |
| Gateway | The single entry point that routes web requests to services |
| Event | A fact that has already happened, published by one service for others to read |
| Outbox | A table in which a service records an event in the same database transaction as the change that caused it |
| Read model | A service's own copy of another service's facts, kept current from events |
| Slice | A piece of the build that is complete from database to screen and can be demonstrated |
