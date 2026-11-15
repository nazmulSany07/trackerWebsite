# 05. Data model

Draft 0.1 · 15 November 2026 · For partner review

This is the logical model: the records each service keeps and how they relate. It shows the important fields, not every column. Exact tables are designed when the slice that needs them is built.

Each service has its own database. Where a record refers to something in another service, such as a user id inside the trading service, it stores the id as a plain value with no database link.

## Rules for all records

| Subject | Rule |
|---|---|
| Money, prices, quantities | Exact decimals. Never floating point |
| Timestamps | Stored in UTC |
| Trading dates | Calendar dates in Dhaka |
| Ideas, trades, transactions, cashflows, audit entries | Insert-only. A correction is a new record, never an overwrite |
| Deleting | Financial records are never deleted. A user account is deactivated, not removed. Retention is open decision B-8 |

## identity

```mermaid
erDiagram
  USER ||--o| STAFF_CREDENTIAL : "has, staff only"
  USER ||--o{ CONSENT : gives
  USER ||--o{ DEVICE : registers
  USER ||--o{ REFRESH_TOKEN : holds

  USER {
    uuid id
    string mobile
    string name
    string role
    string status
    string language
    timestamp created_at
  }
  STAFF_CREDENTIAL {
    uuid user_id
    string username
    string password_hash
  }
  CONSENT {
    uuid user_id
    string channel
    timestamp granted_at
    timestamp withdrawn_at
  }
  DEVICE {
    uuid user_id
    string push_token
    string platform
    timestamp last_seen_at
  }
  REFRESH_TOKEN {
    uuid user_id
    string token_hash
    timestamp expires_at
  }
```

One-time codes are kept in Redis for a few minutes and never stored in the database.

## market

```mermaid
erDiagram
  SYMBOL ||--o{ EOD_QUOTE : "priced by"
  EOD_IMPORT ||--o{ EOD_QUOTE : loaded
  SYMBOL ||--o{ CORPORATE_ACTION : "subject of"
  SYMBOL ||--o| LATEST_QUOTE : "last seen at"

  SYMBOL {
    string trading_code
    string company_name
    string sector
    string category
    string status
  }
  EOD_QUOTE {
    date trading_date
    string trading_code
    decimal open
    decimal high
    decimal low
    decimal close
    decimal volume
    decimal value
    int trades
  }
  EOD_IMPORT {
    uuid id
    date trading_date
    string file_name
    string file_hash
    int rows_accepted
    int rows_rejected
    uuid imported_by
    timestamp imported_at
  }
  CORPORATE_ACTION {
    uuid id
    string trading_code
    string type
    decimal ratio
    decimal rights_price
    date record_date
    date effective_date
  }
  LATEST_QUOTE {
    string trading_code
    decimal price
    decimal volume
    timestamp quoted_at
    string source
  }
  TRADING_DAY {
    date trading_date
    boolean is_open
    time session_start
    time session_end
    string note
  }
```

There is one EOD quote per symbol per trading date, and one import per trading date. The file hash blocks the same file from being loaded twice. `TRADING_DAY` is the session clock: weekends, holidays, and changed hours are rows, not code.

## trading

```mermaid
erDiagram
  IDEA ||--o{ IDEA_UPDATE : "amended by"
  IDEA ||--o| MODEL_POSITION : opens
  MODEL_POSITION ||--o{ MODEL_TRADE : "closed by"
  IDEA ||--o{ FOLLOW : "followed through"
  FOLLOW ||--o{ TRANSACTION : "reported as fills"
  PORTFOLIO ||--o{ MODEL_POSITION : "house book holds"
  PORTFOLIO ||--o{ HOLDING : "client book holds"
  PORTFOLIO ||--o{ TRANSACTION : records
  PORTFOLIO ||--o{ CASHFLOW : funds
  PORTFOLIO ||--o{ UPLOAD : "loaded from"

  IDEA {
    uuid id
    string trading_code
    date analysis_date
    date trading_date
    decimal buy_price
    decimal required_volume
    decimal target_price
    decimal stop_price
    decimal suggested_quantity
    string thesis
    string status
    string status_reason
    uuid published_by
    timestamp published_at
  }
  IDEA_UPDATE {
    uuid id
    uuid idea_id
    string kind
    string note
    decimal new_target
    decimal new_stop
    uuid created_by
    timestamp created_at
  }
  PORTFOLIO {
    uuid id
    string kind
    uuid owner_user_id
    boolean shared_with_desk
  }
  MODEL_POSITION {
    uuid id
    uuid idea_id
    string trading_code
    date entry_date
    decimal entry_price
    decimal quantity
    decimal target_price
    decimal stop_price
    string status
  }
  MODEL_TRADE {
    uuid id
    uuid position_id
    date sell_date
    decimal sell_price
    decimal quantity
    decimal gross
    decimal charges
    decimal net
    string exit_type
    string reason
  }
  HOLDING {
    uuid id
    uuid portfolio_id
    string trading_code
    decimal quantity
    decimal average_cost
  }
  TRANSACTION {
    uuid id
    uuid portfolio_id
    uuid follow_id
    string trading_code
    string type
    date trade_date
    decimal quantity
    decimal price
    decimal charges
    string source
  }
  CASHFLOW {
    uuid id
    uuid portfolio_id
    string kind
    decimal amount
    date flow_date
    string note
  }
  FOLLOW {
    uuid id
    uuid idea_id
    uuid investor_user_id
    string state
    timestamp updated_at
  }
  UPLOAD {
    uuid id
    uuid portfolio_id
    string file_reference
    int rows_accepted
    int rows_rejected
    timestamp uploaded_at
  }
  FEE_SCHEDULE {
    uuid id
    string name
    decimal commission_rate
    date effective_from
  }
  AUDIT_ENTRY {
    uuid id
    uuid user_id
    string action
    string subject
    timestamp at
  }
  OUTBOX {
    uuid id
    string event_type
    string payload
    timestamp created_at
    timestamp sent_at
  }
```

How to read this:

- There is one house portfolio and one client portfolio per investor. `kind` says which.
- The house book is made of model positions, each opened by exactly one idea. A position's current target and stop start as the idea's and change only through an idea update.
- A client book is made of holdings. A holding is the running total of that investor's transactions in one symbol.
- A fill is a transaction that carries a follow id. A transaction with no follow id came from an upload, a manual entry, or a corporate action. `source` records which.
- `FOLLOW` has one row per investor per idea.
- `shared_with_desk` exists only if open decision B-4 is answered yes.
- The track record is calculated from model trades and cashflows. It is not stored separately.

## alerts

```mermaid
erDiagram
  TRIGGER ||--o{ ALERT : fires
  ALERT ||--o{ INBOX_MESSAGE : "shown as"
  ALERT ||--o{ DELIVERY : "sent as"
  CONTACT ||--o{ DELIVERY : receives
  CONTACT ||--o{ INBOX_MESSAGE : reads
  CONTACT ||--|| PREFERENCE : sets
  CONTACT ||--o{ FOLLOWER : "is audience through"

  TRIGGER {
    uuid id
    string owner_kind
    uuid owner_user_id
    uuid idea_id
    string trading_code
    string condition_type
    string parameters
    string status
    date expires_on
  }
  ALERT {
    uuid id
    uuid trigger_id
    string source_event
    string trading_code
    timestamp quote_time
    string message_key
    string message_values
    timestamp created_at
  }
  INBOX_MESSAGE {
    uuid id
    uuid alert_id
    uuid user_id
    timestamp read_at
  }
  DELIVERY {
    uuid id
    uuid alert_id
    uuid user_id
    string channel
    string status
    int attempts
    string provider_reference
    string failure_reason
    timestamp updated_at
  }
  CONTACT {
    uuid user_id
    string mobile
    string language
    boolean whatsapp_consent
    string push_tokens
  }
  PREFERENCE {
    uuid user_id
    string channels
    time quiet_from
    time quiet_to
    string muted_symbols
    boolean daily_digest
  }
  FOLLOWER {
    uuid user_id
    uuid idea_id
    string state
    decimal entry_price
  }
```

How to read this:

- `CONTACT` and `FOLLOWER` are read models. They are copies of facts owned by identity and trading, kept current from events.
- An alert comes either from a trigger firing or directly from an event such as `idea.published`. In the second case `trigger_id` is empty and `source_event` names the event.
- An alert stores a message key and its values, not finished text, so the same alert can be shown in Bangla or English.
- A delivery is unique for one alert, one user, and one channel. An alert is unique for one trigger and one quote time. Together these prevent duplicates.

## From the proof of concept to the new model

| Proof of concept table | Becomes |
|---|---|
| `users` | `USER` and `STAFF_CREDENTIAL` in identity |
| `watchlist` | `IDEA` in trading |
| `positions` | `MODEL_POSITION` in trading |
| `trades` | `MODEL_TRADE` in trading |
| `signals` | Calculated from `position.opened` and `position.closed`. Not a table |
| `cashflows` | `CASHFLOW` on the house portfolio |
| `eod_data` | `EOD_QUOTE` in market |
| `eod_uploads` | `EOD_IMPORT` in market |
| `audit` | `AUDIT_ENTRY` in each service |

Whether the proof of concept's existing trades are loaded into the new model book as its opening history is open decision T-6.
