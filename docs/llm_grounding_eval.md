# LLM grounding evaluation (gemini, model gemini-2.5-flash)

Synthetic data. Acceptance = the reworded answer contained only numbers present in the evidence ledger.

| Question | Accepted / answered | Provider errors | Grounding rejections |
|---|---|---|---|
| Explain the month-over-month cost increase. | 0/0 | 3 |  |
| Which departments are furthest over budget? | 0/0 | 3 |  |
| Summarize the three highest-impact anomalies. | 0/0 | 3 |  |
| Give me the current forecast and its limitations. | 0/0 | 3 |  |
| What optimization actions should we review? | 0/0 | 3 |  |
| How much did we spend in the last complete month? | 0/0 | 3 |  |
| Investigate the cost increase in depth. | 1/1 | 2 |  |

**Grounding acceptance: 1/1 answered calls (100%).** 20 of 21 calls failed at the provider (e.g. rate limits) and are excluded. Rejected or failed answers fall back to the deterministic summary, so a rejection never shows an ungrounded number to the user.
