# 06. Decision log

Draft 0.1 · 15 November 2026 · For partner review

These choices are made. Each entry gives the decision, the reason, and what it costs or commits us to. A decision can be reopened, but only by adding a new entry that replaces the old one.

Questions that are still open are in [Open decisions](10-open-decisions.md).

## Product

### DEC-01. The platform guides and records. It does not trade

**Decision.** No order is sent to a broker. An investor trades through their own broker and records the fill on the platform.

**Why.** Routing orders needs broker integrations and a different regulatory position. Guidance and tracking deliver the product's value without either.

**Consequence.** An investor's results on the platform are as accurate as what they enter. The track record must distinguish the model book from what investors actually did.

### DEC-02. A published idea is never edited

**Decision.** After publication an idea's values are fixed. Changes are added as dated updates.

**Why.** The track record is only credible if no one, including us, can quietly change an entry price, target, or stop after the fact.

**Consequence.** A mistake in a published idea is corrected by an update or by withdrawing the idea. Both stay visible.

### DEC-03. Exit alerts go to investors who reported buying

**Decision.** Target, stop, and exit alerts for an idea are sent to investors whose follow is Bought or Partial.

**Why.** Telling people to sell a stock they never bought teaches them to ignore alerts.

**Consequence.** The follow confirmation is a core feature, not an extra. Investors must find it quick to record a fill.

### DEC-04. The in-app inbox is the record of every alert

**Decision.** Every alert is written to the inbox first. WhatsApp and phone push are additional channels.

**Why.** WhatsApp and push both fail in normal operation. The investor must always be able to find the alert.

**Consequence.** Telegram, used by the proof of concept, is not an investor channel and is not in version 1.

### DEC-05. Web app first, usable on a phone

**Decision.** Version 1 is a web app that works on phone and desktop. A native app comes later, if at all.

**Why.** One codebase reaches every user, and the desk's dense tables suit a web app.

**Consequence.** Phone push from a web app works on Android browsers. On an iPhone it works only after the user adds the web app to the home screen. WhatsApp covers users who do not.

## Architecture

### DEC-06. The backend is four Spring Boot services behind a gateway

**Decision.** identity, market, trading, alerts, and a gateway, in Java 21 with Spring Boot 3.

**Why.** Chosen by the founder for a service-based platform on a mainstream enterprise stack. Four is the smallest split that follows real boundaries: sign-in, market data, the trading record, and outbound messaging.

**Consequence.** Running several services costs more than running one application: more deployment, more monitoring, and events to reason about. This is the main engineering risk for a small team (see risk R-05). Request ids, structured logs, and the outbox are required from the first slice, not added later. The number of services does not grow with features.

### DEC-07. Ideas, books, and follows live in one service

**Decision.** The trading service owns ideas, the model book, client books, follows, and fills.

**Why.** Confirming a fill changes the follow, a transaction, and a holding together. In one service that is one database transaction.

**Consequence.** The trading service is the largest. It is organised internally by area so that it stays readable.

### DEC-08. Each service owns its database, and services share facts through events

**Decision.** No service reads another's database. Facts travel as events on RabbitMQ, written through an outbox.

**Why.** It keeps each service changeable on its own and lets alerts keep sending while another service restarts.

**Consequence.** Some data exists in two places: the alerts service holds a copy of followers and contacts. Readers must tolerate an event arriving twice or a moment late.

### DEC-09. RabbitMQ is the message broker

**Decision.** RabbitMQ carries all events.

**Why.** Until the live feed exists, event volume is a few thousand a day. RabbitMQ handles that with little to operate and is well supported in Spring.

**Consequence.** If live quotes reach high volume, the quote path is reviewed at that point. Other events stay as they are.

### DEC-10. PostgreSQL with exact decimals

**Decision.** PostgreSQL 16. Money, prices, and quantities are exact decimals in the database and in Java.

**Why.** The proof of concept stores prices as floating point, which accumulates rounding errors in cash and profit figures.

**Consequence.** One PostgreSQL server holds the four databases to start. They can move to separate servers without code changes.

### DEC-11. Quotes come from one place

**Decision.** Only the market service knows where a price came from. Other services receive quotes as events.

**Why.** The live feed can then replace the EOD file without changing trading rules or triggers.

**Consequence.** The trading and alerts rules must be written against a quote and its time, never against "today's file".

## Web app

### DEC-12. Next.js with React and TypeScript

**Decision.** One Next.js application using the App Router serves both the desk and investors.

**Why.** It is the most widely used React framework, with established patterns for sign-in, languages, and hosting. Its server holds the session cookie so the browser never calls a service directly.

**Consequence.** Routing belongs to Next.js. TanStack Router and TanStack Start are not used.

### DEC-13. TanStack Query, Table, and Form inside Next.js

**Decision.** TanStack Query for server data, TanStack Table for tables, TanStack Form with Zod for forms. TanStack Virtual is added where a list becomes long.

**Why.** The app is mostly tables and forms over an API, which is what these libraries are for. They are headless, so the existing design tokens apply.

**Consequence.** The TypeScript API client and validation types are generated from the services' OpenAPI specifications, not written by hand.

## Access

### DEC-14. Investors sign in by mobile number, staff by password

**Decision.** Investors use a mobile number and a one-time code sent by SMS. Staff use a username and password.

**Why.** A mobile number is how investors in Bangladesh are identified, and it is the number WhatsApp alerts go to.

**Consequence.** An SMS gateway is a launch dependency and a running cost. One-time code requests must be rate limited.

## Delivery

### DEC-15. The proof of concept's rules are ported, not its code

**Decision.** The buy, sell, cash, and expiry rules are rewritten in the trading service with tests. The Flask application and its SQLite database are not reused.

**Why.** The rules are proven. The code is single-user, stores money as floating point, and creates a default admin password.

**Consequence.** The first trading slice is finished when the new service reproduces the proof of concept's results on the same input.

### DEC-16. A written baseline first, then working slices

**Decision.** These documents come before code. The build then proceeds in slices that are each complete from database to screen and demonstrated in staging.

**Why.** The baseline fixes scope, vocabulary, and boundaries. Slices prove each part works before the next is started.

**Consequence.** API specifications and the runbook are produced during the build, from running software.

### DEC-17. One server and Docker Compose to start

**Decision.** Staging and production each run the whole platform on one virtual server with Docker Compose, in Singapore or Mumbai.

**Why.** It is enough for EOD-driven load and is simple to operate.

**Consequence.** One server is a single point of failure (see risk R-09). Backups and a tested restore are required before launch. Hosting is reviewed when the live feed arrives.
