# 01. Product brief

Draft 0.1 · 15 November 2026 · For partner review

## What we are building

A web platform for investors and traders on the Dhaka Stock Exchange (DSE). Our desk publishes trade ideas and runs a model book that investors can inspect. Investors follow those ideas, record what they actually bought and sold, keep their own portfolio on the platform, and receive an alert by WhatsApp, phone push, or in-app inbox when a price level is reached.

The platform links two things that are normally separate: the track we publish, and what each investor really holds.

## Who uses it

| User | Who they are | What they need |
|---|---|---|
| Investor | An individual investor or professional trader on DSE | Our ideas with reasons, their own portfolio in one place, and an alert when a level they care about is reached |
| Analyst | A member of our desk who researches and publishes ideas | A fast way to publish an idea, update it, and see who followed it |
| Admin | The desk owner | Everything an analyst has, plus users, market data, capital, and the audit log |

"The desk" means admins and analysts together.

## Three ways an investor uses it

| Mode | What the investor does | What the platform does |
|---|---|---|
| Follow us | Reads our ideas and marks what they did: bought, skipped, or sold | Sends idea, update, and exit alerts. Exit alerts go only to investors who reported buying |
| Track their own book | Uploads or types in their holdings and sets their own triggers | Values the portfolio, tracks profit and loss, and alerts on their triggers |
| Both | Does both of the above | Shows the overlap: stocks both hold, stocks only the investor holds, and desk ideas the investor has not taken |

## What the platform does not do

- It does not send orders to a broker. An investor trades through their own broker and then records the fill here.
- It does not hold or move client money. Cash figures are a record entered by the user.
- It is not a social network. Investors do not see each other's portfolios.
- It does not generate trade calls automatically. Every idea is written and published by a named analyst.

## Features

### Version 1

| Area | Feature |
|---|---|
| Accounts | Investor sign-in by mobile number and one-time code. Staff sign-in by username and password. Three roles: admin, analyst, investor |
| Ideas | Analyst publishes an idea with symbol, trading date, buy level, required volume, target, stop, suggested quantity, and a written reason. A published idea is never edited. Changes are added as dated updates |
| Model book | The portfolio that results from applying every idea by fixed rules. Shows open positions, closed trades, cash, and equity |
| Client book | Investor uploads a broker spreadsheet or enters holdings by hand. Shows quantity, average cost, market value, and profit and loss after charges |
| Follow | Per idea, the investor records Following, Bought, Skipped, Partial, or Exited, with their own price and quantity |
| Overlap | Side-by-side view of the investor's book against the model book |
| Corporate actions | Bonus shares, rights shares, and splits adjust quantity and cost in both books |
| Market data | Daily end-of-day (EOD) file import with duplicate detection and column mapping. Symbol list and trading calendar |
| Triggers | Conditions on price or volume, set by the desk on an idea or by an investor on any symbol. See the trigger table below |
| Alerts | In-app inbox, WhatsApp, and phone push. Per-user channel choice, quiet hours, and symbol mute. Every send is logged with its outcome |
| Track record | Win rate, average gain and loss, holding time, monthly profit and loss, and drawdown for the model book, measured from the time each idea was published |
| Language | Bangla and English |
| Audit | Every change to money, positions, or ideas is logged with who and when |

### Triggers in version 1

| Trigger | Fires when |
|---|---|
| Price crosses a level | Price moves above or below a set price |
| Near target or stop | Price comes within a set percentage of an idea's target or stop |
| Target hit, stop hit | The model book rule closes a position |
| Percent move | Price moves a set percentage from the investor's entry price or from the day's open |
| Volume | Volume reaches a set amount or a multiple of the recent average |
| Idea expiry | An idea is not filled by its trading date |

Until a live price feed exists, triggers are evaluated once a day against the EOD file. The triggers do not change when the live feed arrives. Only the source of prices changes.

### After version 1

| Feature | Note |
|---|---|
| Live DSE prices | Needs a licensed data source. See open decisions |
| Trailing stop and portfolio-level triggers | For example, one stock exceeding a share of the book, or a daily loss limit |
| Risk-based position size | Suggested quantity from the investor's capital and the idea's stop distance |
| Comparison with DSEX | Model book and client book return against the index |
| Risk profile | Conservative, moderate, or aggressive, to filter ideas and scale size |
| Sector and concentration view | Breakdown of the investor's book |
| Questions on an idea | Investor asks, analyst answers, attached to the idea |
| Subscription and billing | Depends on the business model |
| Native mobile app | The web app works on phones from version 1 |

## Rules carried over from the proof of concept

The current tracker already runs these rules for one user. They become the model book rules, rewritten in the new platform and covered by tests.

| Rule | How the proof of concept applies it |
|---|---|
| Buy | On the idea's trading date, the position opens only if the day's close is at or above the buy price and the day's volume is at or above the required volume. The entry is recorded at the day's close |
| Cash check | The buy is rejected if its cost exceeds available cash |
| One position per symbol | A second idea on a symbol with an open position is rejected |
| Sell at target | The position closes when the day's high reaches the target |
| Sell at stop | The position closes when the day's close is at or below the stop |
| Order within a day | Sells are processed before buys. A position cannot be sold on the day it was bought |
| Expiry | An idea that fails the buy rule, or has no price for its trading date, expires with the reason recorded |
| Manual sell | A full or partial sell with a price, date, and charges |
| Capital | Deposits and withdrawals. Available cash is deposits minus withdrawals minus the cost of open positions plus realised profit |
| Trading week | Friday and Saturday are closed |

One behaviour needs a partner decision before it is copied: a target sell is detected on the day's high but recorded at the day's close, so the recorded exit can be below the target. See [Open decisions](10-open-decisions.md), item T-1.

## How we will know it works

The partners should set a target for each of these before launch:

- Investors who have confirmed at least one fill on an idea.
- Investors who have uploaded or entered a portfolio.
- Share of alerts delivered on the investor's chosen channel.
- Time from a price being stored to the alert being sent.
- Model book results, measured from publication time.
