# 03. Users and journeys

Draft 0.1 · 15 November 2026 · For partner review

This document shows who uses the platform, what each role may do, and how the main tasks flow from start to finish. Each journey ends in acceptance checks a tester can run.

## Roles and what they do

```mermaid
flowchart LR
  INV(["Investor"])
  ANA(["Analyst"])
  ADM(["Admin"])

  subgraph ACC["Account"]
    U1["Sign in"]
    U2["Set language, channels, quiet hours"]
  end

  subgraph IDE["Ideas"]
    U3["Read ideas and updates"]
    U4["Follow an idea and report fills"]
    U5["Write and publish an idea"]
    U6["Add an update or withdraw an idea"]
  end

  subgraph BOO["Books"]
    U7["Upload or enter own portfolio"]
    U8["Compare own book with model book"]
    U9["View model book and track record"]
    U10["Manual sell in model book"]
    U11["Record model book capital"]
  end

  subgraph ALE["Alerts"]
    U12["Set own triggers"]
    U13["Receive alerts"]
    U14["Set triggers on an idea"]
    U15["View delivery log"]
  end

  subgraph ADMIN["Administration"]
    U16["Import EOD file"]
    U17["Maintain symbols, calendar, corporate actions"]
    U18["Manage users and roles"]
    U19["View audit log"]
  end

  INV --> U1 & U2 & U3 & U4 & U7 & U8 & U9 & U12 & U13
  ANA --> U1 & U3 & U5 & U6 & U9 & U10 & U14 & U15
  ADM --> U5 & U6 & U10 & U11 & U14 & U15 & U16 & U17 & U18 & U19
```

An admin can do everything an analyst can. The diagram shows the admin's additional tasks and the shared publishing tasks.

### Permissions

| Action | Investor | Analyst | Admin |
|---|---|---|---|
| Read published ideas, updates, model book, and track record | Yes | Yes | Yes |
| Record a follow and fills on own account | Yes | No | No |
| Keep a client book: upload, edit, own triggers | Yes | No | No |
| See another investor's client book | No | See note | See note |
| Draft, publish, update, or withdraw an idea | No | Yes | Yes |
| Manual sell in the model book | No | Yes | Yes |
| Deposit or withdraw in the model book | No | No | Yes |
| Import EOD file. Maintain symbols, calendar, corporate actions | No | No | Yes |
| See how many investors followed, bought, or skipped an idea | No | Yes | Yes |
| See the alert delivery log | Own inbox only | Yes | Yes |
| Manage users and roles | No | No | Yes |
| Read the audit log | No | No | Yes |

Note: whether the desk can see an individual investor's book is an open decision (B-4). The recommendation is that a book is private unless the investor chooses to share it with the desk for guidance.

## Journey 1: An investor joins

```mermaid
flowchart TD
  A["Enter mobile number"] --> B["Receive one-time code by SMS"]
  B --> C{"Code correct and in time?"}
  C -- No --> C1["Show error, allow a limited number of retries"] --> B
  C -- Yes --> D["Enter name, choose Bangla or English"]
  D --> E["Read and accept terms and the guidance disclaimer"]
  E --> F{"Receive alerts on WhatsApp?"}
  F -- Yes --> F1["Record consent with date and time"] --> G
  F -- No --> G{"Allow phone push?"}
  G -- Yes --> G1["Register this device"] --> H
  G -- No --> H{"Add a portfolio now?"}
  H -- Upload --> H1["Go to portfolio upload"]
  H -- Enter by hand --> H2["Go to add holding"]
  H -- Later --> I["Home: ideas, inbox, portfolio summary"]
  H1 --> I
  H2 --> I
```

## Journey 2: The desk's trading day

Until a live feed exists, the whole platform advances once per trading day, when the admin imports the EOD file.

```mermaid
flowchart TD
  A["Admin uploads the day's EOD file"] --> B{"Same file or date already imported?"}
  B -- Yes --> B1["Reject as duplicate, change nothing"]
  B -- No --> C{"All required columns recognised?"}
  C -- No --> C1["Admin maps the columns by hand"] --> D
  C -- Yes --> D["Store quotes, list invalid rows"]
  D --> E["Model book: close positions that hit target or stop"]
  E --> F["Model book: open positions for ideas due today that pass the buy rule"]
  F --> G["Expire ideas due today that failed, with the reason"]
  G --> H["Evaluate desk and investor triggers on the new quotes"]
  H --> I["Send alerts to the right audience"]
  I --> J["Books, dashboards, and track record show the new day"]
```

## Journey 3: An idea from draft to close

### Life of an idea

```mermaid
stateDiagram-v2
  [*] --> Draft
  Draft --> Published: Analyst publishes
  Published --> Open: Buy rule passes on the trading date
  Published --> Expired: Buy rule fails or no quote
  Published --> Withdrawn: Desk withdraws before the trading date
  Open --> Open: Partial manual sell
  Open --> Closed: Target hit, stop hit, or full manual sell
  Expired --> [*]
  Withdrawn --> [*]
  Closed --> [*]
```

Only a draft can be edited. From Published onward, the original values are fixed and every change is a dated update that investors can see.

### Publishing an idea

```mermaid
sequenceDiagram
  actor Analyst
  participant Web as Web app
  participant TR as trading service
  participant MQ as RabbitMQ
  participant AL as alerts service
  participant CH as WhatsApp and push
  actor Investor

  Analyst->>Web: Fill in idea and publish
  Web->>TR: Publish idea
  TR->>TR: Save idea, audit row, and outbox row in one transaction
  TR-->>Web: Published, with time and analyst name
  TR->>MQ: idea.published
  MQ->>AL: idea.published
  AL->>AL: Work out the audience and each person's channels
  AL->>AL: Write an inbox message for each recipient
  AL->>CH: Send
  CH-->>Investor: New idea
  CH-->>AL: Delivered or failed
```

## Journey 4: An investor follows an idea

### States of a follow

```mermaid
stateDiagram-v2
  [*] --> Following: Investor follows the idea
  [*] --> Bought: Investor reports a buy directly
  Following --> Bought: Reports a buy
  Following --> Skipped: Marks as skipped
  Bought --> Partial: Reports selling part
  Partial --> Partial: Reports selling more
  Bought --> Exited: Reports selling all
  Partial --> Exited: Reports selling the rest
  Skipped --> [*]
  Exited --> [*]
```

### Confirming a buy

```mermaid
sequenceDiagram
  actor Investor
  participant Web as Web app
  participant TR as trading service
  participant MQ as RabbitMQ
  participant AL as alerts service

  Investor->>Web: Open the idea and choose I bought
  Web->>TR: Record fill with date, price, and quantity
  TR->>TR: Save follow state, transaction, holding, audit row, outbox row in one transaction
  TR-->>Web: Follow is Bought and the client book is updated
  TR->>MQ: follow.confirmed
  MQ->>AL: follow.confirmed
  AL->>AL: Add this investor to the exit audience for the idea
  Note over AL: Target, stop, and exit alerts for this idea now reach this investor
```

The fill updates the follow and the investor's book in one step, inside one service. That is why both live in the trading service.

## Journey 5: An investor loads their portfolio

```mermaid
flowchart TD
  A["Investor chooses a broker spreadsheet"] --> B["Platform reads the file"]
  B --> C{"Columns recognised?"}
  C -- No --> C1["Investor matches columns: symbol, quantity, average cost"] --> D
  C -- Yes --> D["Match each row to a DSE symbol"]
  D --> E["Show preview: rows accepted, rows rejected with reason"]
  E --> F{"Investor confirms?"}
  F -- No --> F1["Discard, nothing changes"]
  F -- Yes --> G["Save holdings and record the upload"]
  G --> H["Show the book: value, profit and loss after charges"]
  H --> I["Show overlap with the model book"]
```

The investor can also add, edit, or remove a holding by hand at any time.

The overlap view has three lists:

| List | Meaning |
|---|---|
| Both hold | Stocks in the client book that are open positions in the model book |
| Only you hold | Stocks in the client book that the model book does not hold |
| Only the model book holds | Open desk ideas the investor has not taken |

## Journey 6: A trigger becomes an alert

```mermaid
sequenceDiagram
  participant MK as market service
  participant MQ as RabbitMQ
  participant AL as alerts service
  participant CH as WhatsApp and push
  actor Investor

  MK->>MQ: New quotes stored
  MQ->>AL: New quotes stored
  AL->>AL: Check each quote against the session clock
  alt Quote is stale or outside the session
    AL->>AL: Hold the trigger, record the reason, send nothing
  else Quote is fresh
    AL->>AL: Find triggers whose condition is met
    AL->>AL: Create the alert once per trigger and quote time
    AL->>AL: Write an inbox message for each recipient
    AL->>CH: Send on each chosen channel unless in quiet hours
    CH-->>Investor: Alert
    CH-->>AL: Delivered or failed
    AL->>AL: Record the outcome and retry failures
  end
```

### Who receives which alert

| Alert | Recipients |
|---|---|
| New idea published | All active investors who have not muted the symbol. May change with the business model: see open decision B-1 |
| Idea update, such as a moved stop | Investors whose follow is Following, Bought, or Partial |
| Model book bought | Investors whose follow is Following |
| Near target or near stop | Investors whose follow is Bought or Partial |
| Model book sold at target or stop | Investors whose follow is Bought or Partial. Following investors see it in the inbox only |
| Idea expired or withdrawn | Investors whose follow is Following |
| An investor's own trigger | That investor |

An investor who skipped or exited an idea receives nothing further about it.

### Life of one delivery

A delivery is one alert, to one user, on one channel.

```mermaid
stateDiagram-v2
  [*] --> Queued
  Queued --> Deferred: Quiet hours
  Deferred --> Queued: Quiet hours end
  Queued --> Sent: Provider accepts
  Sent --> Delivered: Provider confirms
  Delivered --> Read: User opens it
  Queued --> Failed: Provider rejects or times out
  Sent --> Failed: Provider reports failure
  Failed --> Queued: Retry
  Failed --> Abandoned: Retries used up
  Delivered --> [*]
  Read --> [*]
  Abandoned --> [*]
```

The inbox message is written before any WhatsApp or push send, so an abandoned delivery never means a lost alert.

## Acceptance checks

Each check is a test the team writes and a tester can repeat in staging.

### Accounts

| # | Check |
|---|---|
| AC-01 | An investor signs in with a mobile number and one-time code. A wrong or expired code is refused. Repeated code requests from one number are blocked |
| AC-02 | An investor cannot open a desk screen or call a desk action, even with a hand-typed address |

### Ideas and the model book

| # | Check |
|---|---|
| AC-03 | A published idea cannot be edited. An update appears as a dated note and the original values stay visible |
| AC-04 | On the trading date, a position opens only if the close is at or above the buy price and the volume is at or above the required volume. Otherwise the idea expires and the reason names the failed condition |
| AC-05 | A buy whose cost exceeds available cash is rejected with the amount needed |
| AC-06 | A second idea on a symbol with an open position is rejected |
| AC-07 | A position closes when the day's high reaches the target, or when the day's close is at or below the stop. Neither can happen on the entry day |
| AC-08 | Importing the same EOD file, or a second file for the same date, is refused and changes nothing |
| AC-09 | A partial manual sell reduces the quantity and records a trade with charges. A full sell closes the position |
| AC-10 | After every deposit, withdrawal, buy, and sell, available cash and equity match their definitions in the glossary |

### Client book

| # | Check |
|---|---|
| AC-11 | A broker file with unfamiliar column names can be mapped by hand. Accepted rows appear with the right quantity and average cost. Rejected rows are listed and not saved |
| AC-12 | A bonus issue or split changes quantity and average cost and leaves total cost unchanged. A rights issue adds quantity at the rights price |
| AC-13 | Confirming a buy sets the follow to Bought and changes only that investor's book |
| AC-14 | The overlap view puts every stock in the correct one of its three lists |
| AC-15 | An investor cannot read another investor's book through any screen or direct request |

### Alerts

| # | Check |
|---|---|
| AC-16 | A target or stop alert reaches investors whose follow is Bought or Partial, and no one whose follow is Skipped or Exited |
| AC-17 | The same trigger and quote time never produce two alerts to the same user on the same channel |
| AC-18 | A stale or off-session quote fires no trigger, and the hold is recorded |
| AC-19 | WhatsApp is sent only to investors who gave consent. Withdrawing consent stops it immediately |
| AC-20 | A failed WhatsApp send is retried, appears as failed in the delivery log, and the inbox still holds the message |
| AC-21 | In quiet hours no WhatsApp or push is sent. The inbox receives the message at once |

### Whole platform

| # | Check |
|---|---|
| AC-22 | Every change to money, a position, a holding, or an idea has an audit entry with the user and the time |
| AC-23 | Every screen is available in Bangla and English |
