# 10. Open decisions

Draft 0.1 · 15 November 2026 · For partner review

These questions are not answered yet. Each one changes what is built or when it can launch. The partners should assign an owner and a date to each. When one is answered, it moves to the [Decision log](06-decision-log.md).

The "Needed by" column refers to the slices in the [Delivery plan](08-delivery-plan.md). An item marked "Start now" has a long lead time outside our control.

## Business

| # | Question | Why it matters | Recommendation | Needed by |
|---|---|---|---|---|
| B-1 | What is the business model: free, subscription, or tiers? Who receives new ideas? | Decides whether all investors get every idea, and whether billing is built | Launch free to a closed group of investors, and decide pricing from how they use it | Slice 5 |
| B-2 | What is our legal position for publishing trade guidance, and for charging for it? | Could delay launch or change the product | Take legal advice on securities regulation and on data protection before any investor is invited | Start now. Blocks launch |
| B-3 | What is the platform called? | Needed for the domain, the WhatsApp business profile, and the SMS sender name | Decide before applying for the WhatsApp account | Before D-3 |
| B-4 | Can the desk see an individual investor's portfolio? | Decides whether we can give personal guidance, and how private a book is | Private by default. The investor can switch on sharing with the desk and switch it off again | Slice 4 |
| B-5 | Who may publish an idea? Does a second person approve it first? | Affects the idea screens and the credibility of the track record | Named analysts publish under their own name. No approval step in version 1 | Slice 3 |
| B-6 | What do investors see of the model book: amounts in taka, or only percentages and prices? | Showing the desk's capital is a business choice | Show prices, percentages, and dates. Keep taka amounts for the desk | Slice 4 |
| B-7 | Who answers investors' questions, and where? | Questions will arrive by WhatsApp reply from the first alert | Name a support contact and a response time. Do not build chat in version 1 | Slice 6 |
| B-8 | How long are records kept, and what happens when an investor asks to leave? | Financial records and personal data pull in opposite directions | Deactivate the account, keep the financial record for the period the lawyer advises | Slice 7 |
| B-9 | What are the success targets for the first months? | Tells us whether version 1 worked | Set a target for each measure in the product brief | Before launch |

## Trading rules

| # | Question | Why it matters | Recommendation | Needed by |
|---|---|---|---|---|
| T-1 | When a target is reached, at what price is the model book's sale recorded? | The proof of concept detects the target on the day's high but records the sale at the day's close, which can be below the target | Decide whether the record should show the target price or the close. The trading lead should choose the one a follower could really have achieved | Slice 3 |
| T-2 | At what price is the model book's entry recorded? | The proof of concept uses the day's close. With live prices there will be an actual trigger moment | Keep the close for EOD. Define the live rule under T-8 | Slice 3 |
| T-3 | Are charges applied to the model book's automatic trades? | The proof of concept records zero charges on automatic sells and none on buys, so its results are before costs | Apply a standard fee schedule to every model trade, so published results are after costs | Slice 3 |
| T-4 | Does a book respect settlement, so that shares bought cannot be sold until they mature? | On DSE, shares cannot be sold until settlement, which is typically two trading days and varies by category. The proof of concept only blocks a sale on the entry day | Apply the settlement period in the model book. Warn, but do not block, in a client book | Slice 4 |
| T-5 | How are rights issues handled? | Rights are optional and cost money, unlike bonus shares | The model book states for each rights issue whether it subscribes. An investor confirms their own choice | Slice 4 |
| T-6 | Is the proof of concept's trade history loaded into the new model book? | Decides whether the track record starts with history or from zero | Load it, marked as recorded before the platform, so the track record is honest about its source | Slice 3 |
| T-7 | Is there one model book, or several, such as short-term and long-term? | Changes ideas, follows, and the track record | One book in version 1. The data model allows more later | Slice 3 |
| T-8 | With live prices, do target and stop act on the first touch during the session, or on the close? | The proof of concept acts on the day's high for targets and the day's close for stops | Decide with the trading lead before the live feed is built | Live feed |
| T-9 | If a day's prices meet both the target and the stop, which applies? | The proof of concept applies the target | Confirm, or choose the more cautious result | Slice 3 |

## Data and providers

| # | Question | Why it matters | Recommendation | Needed by |
|---|---|---|---|---|
| D-1 | Where does the daily EOD file come from, who uploads it, and by what time? | The whole platform advances on this file | Name one person and a backup, and a time after which the team is alerted | Slice 3 |
| D-2 | Which licensed source will supply live DSE prices, and may we show them to investors? | Without it there are no intraday alerts | Open the conversation with DSE or a licensed data vendor now, and check redistribution terms | Start now |
| D-3 | Who owns the WhatsApp business account, and which number and templates will it use? | Business verification and template approval are done by Meta and take time. Messages are charged | Apply as soon as the name is decided. Keep templates to alerts the investor asked for | Start by slice 3 |
| D-4 | Which SMS gateway sends one-time codes? | A launch dependency and a running cost | Choose a provider with delivery reports and a registered sender name | Slice 2 for production |
| D-5 | Who enters corporate actions, and from what source? | A missed or wrong entry corrupts every affected book | One named owner, working from DSE announcements, with a second person checking | Slice 4 |
| D-6 | Where will DSEX index values come from? | Needed for the later comparison with the index | Check whether the EOD source includes the index | After version 1 |

## Engineering

| # | Question | Why it matters | Recommendation | Needed by |
|---|---|---|---|---|
| E-1 | Where is the code hosted, and what runs the automated build? | Needed on the first day | Use one hosted service for both | Slice 1 |
| E-2 | Which hosting provider, and who operates production? | Someone must be responsible for backups, releases, and incidents | One virtual server in Singapore or Mumbai, with a named operator | Slice 1 |
| E-3 | Who builds the platform: in-house, a firm, or both? | Drives cost, time, and who maintains it afterwards | Whoever builds it, keep the trading lead and product owner in-house | Before slice 1 |
| E-4 | Are the proposed service targets accepted? | They set the cost of hosting and operations | Review the targets in [Quality, security, and risk](07-quality-security-risk.md) | Slice 7 |
| E-5 | Which browsers and phones must be supported? | Affects testing and the push feature | Current Chrome on Android, current Safari on iPhone, and current desktop browsers | Slice 2 |

## What to do first

Three items have lead times we do not control and should be started before any code is written:

1. Legal advice on publishing guidance and on data protection (B-2).
2. The licensed live price source (D-2).
3. The platform's name, and then the WhatsApp business account (B-3, D-3).

Four items change the model book's rules and need the trading lead before slice 3 starts: T-1, T-2, T-3, and T-9.
