# ADR-014: Detection scope: English only, explicit entities

Status: Accepted, 2026-10-24

Plan decisions: 25, 26, 27

## Context

The English NLP model misses names in other languages, and French is an official language in Canada. Broad entity types such as LOCATION flood marketing copy with false positives.

## Decision

Detect English only, and treat everything else as undetectable: text with any non-Latin script, or with at least three French or Spanish function words outnumbering English ones, is `language_unsupported` and handled as high sensitivity (rerouted from cloud and DeepSeek, passed locally). Entities are listed explicitly in the policy: high is CA_SIN, CREDIT_CARD, CA_BANK_ACCOUNT, IBAN_CODE; general is PERSON, PHONE_NUMBER, EMAIL_ADDRESS, CA_POSTAL_CODE, STREET_ADDRESS. City names, dates, URLs and organisation names are not PII. SIN uses a custom recognizer plus a Luhn check in the plugin; the US SSN recognizer is removed because it mislabels SINs; the score threshold is 0.4.

## Alternatives rejected

- **Detecting English and passing everything else.** Chinese PII would leave silently.
- **Judging language by script only.** French names would be missed.
- **spaCy LOCATION as address.** City names in marketing copy would be flagged constantly.

## Consequences

On a 19-case synthetic English corpus the detector found 16/16 entity instances with no false positives. That is a regression test, not a benchmark; misses will be recorded as they are found. Chinese PII detection is a later enhancement.

Evidence: [`docs/p4-results.md`](../p4-results.md)
