# GEO/AEO portfolio audit runbook

This repository includes a dependency-free technical audit runner. It checks observable crawl and answer-surface facts; it does not pretend to measure rankings, citation share, factual truth, or conversion performance.

## Run it

```bash
python3 scripts/geo_aeo_audit.py \
  --config portfolio.json \
  --output audit/latest.json \
  --markdown audit/latest.md
```

The command exits non-zero for technical errors such as a failed fetch, missing canonical, invalid H1 count, blocked search/retrieval crawler, or empty/unreadable sitemap. Review warnings manually.

## What it checks

- live homepage status and final URL;
- title, description, canonical URL, H1 count, word count, and JSON-LD types;
- Google Preferred Sources control on configured publisher candidates;
- `robots.txt` access for normal search and current AI search/retrieval agents;
- training-crawler posture, reported separately from search eligibility;
- sitemap URL count and suspicious uniform/today-only `lastmod` values;
- configured high-risk phrases that require a human evidence review.

## What it deliberately does not claim

- that a URL is indexed merely because it can be fetched;
- that a page ranks or is cited by an answer engine;
- that schema creates a ranking advantage;
- that a business, legal, medical, rating, review, or recovery claim is true;
- that `llms.txt` is required;
- that one prompt run represents stable citation behavior.

## Human verification gates

After every run:

1. Verify critical claims against primary sources and store source URL, observed date, reviewer, and expiry date.
2. Check Search Console and Bing Webmaster Tools for index coverage and query/page changes.
3. Inspect server/CDN logs for verified crawler IP and user-agent combinations.
4. Repeat a fixed answer-engine prompt set across multiple runs and record the cited URL, not merely the cited domain.
5. Treat medical, legal, financial, rating, review, and "verified" assertions as release blockers when evidence is missing.

## Google generative-AI measurement

As of 2026-08-31, Search Console's dedicated Generative AI performance reports are available worldwide for Search and Discover. Review impressions, surfaced pages, countries, devices (Search), and time trends as a separate first-party visibility lane.

Do not represent this report as automated by the Search Analytics API. The API's current `type` values are `discover`, `googleNews`, `news`, `image`, `video`, and `web`; there is no dedicated generative-AI type or dimension as of 2026-09-02. Use the Search Console UI or an operator-approved export until Google documents API support.

The separate Search generative AI control is a consequential site policy. Audit and report its state, but do not change it automatically. Exclusion affects Google's generative-AI Search features, not other Search surfaces or model training; Google-Extended remains the training control.

Sources: [Google's report announcement and worldwide rollout note](https://developers.google.com/search/blog/2026/06/gen-ai-performance-reports), [Search Analytics API](https://developers.google.com/webmaster-tools/v1/searchanalytics/query), and [Search generative AI control](https://support.google.com/webmasters/answer/16908024).

## Cloudflare preference synchronization

For Cloudflare-hosted properties, inspect whether Bot Preference Sync and the zone's Search, Agent, and Training choices match the intended policy. The feature can derive `robots.txt` directives from zone policy, but enabling or changing it is an operator decision. Never switch it during a read-only audit.

Source: [Cloudflare Bot Preference Sync](https://blog.cloudflare.com/bot-preference-sync/) and the [zone Bot Management API](https://developers.cloudflare.com/api/resources/bot_management/methods/get/).

## Scheduled run

The GitHub Actions workflow runs at 8:00 AM America/Chicago on the first Monday of each month, accounting for daylight-saving time with a no-op gate. It uploads the JSON and Markdown results as workflow artifacts; it does not commit generated files, deploy sites, change crawler policies, or update Search Console.

## Current official crawler roles

| Purpose | OpenAI | Anthropic | Perplexity | Google |
| --- | --- | --- | --- | --- |
| Search/index | `OAI-SearchBot` | `Claude-SearchBot` | `PerplexityBot` | `Googlebot` |
| User fetch | `ChatGPT-User` | `Claude-User` | `Perplexity-User` | normal Search fetch paths |
| Training/control token | `GPTBot` | `ClaudeBot` | no search bot used for training | `Google-Extended` |

Sources: [OpenAI](https://developers.openai.com/api/docs/bots), [Anthropic](https://support.claude.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler), [Perplexity](https://docs.perplexity.ai/docs/resources/perplexity-crawlers), and [Google](https://developers.google.com/search/docs/appearance/ai-features).
