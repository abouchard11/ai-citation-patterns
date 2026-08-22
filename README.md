# AI Citation Patterns — a 2026 GEO reference

*How the major AI answer engines actually select and cite content — dated, sourced, and honestly
caveated. Researched and maintained by [Alex Bouchard](https://github.com/abouchard11) (MidnightDev).*

> **Freshness note (verification pass 2026-07-16):** platform-behavior sections were last fully
> verified Mar–Apr 2026; Google's 2026-05-27 AI Overviews/AI Mode update is captured in the dated
> addendum below. Content-structure and query-type sections age slowly and remain current.
>
> **Verification discipline:** AI citation behavior drifts in *months*, not years — model
> transitions, crawler changes, and feature launches happen quarterly. Before relying on anything
> here for a content decision, verify against primary sources, especially model names, launch
> dates, citation counts, and ranking-signal claims. Each section lists its verification date and
> sources. When you update a section, re-verify — don't patch from memory.

---

## Google AI Overviews / AI Mode

> **UPDATE 2026-05-27 (verified 2026-07-16; sources: blog.google, Search Engine Land, Nieman Lab):**
> Google shipped four citation-surface changes that alter optimization tactics:
> 1. **Preferred Sources now appear inside AI Overviews & AI Mode**, clearly labeled; users are ~2×
>    as likely to click a Preferred Source (345K+ unique sources selected). New lever: prompt loyal
>    audiences (email list, social) to add your site as a Preferred Source.
> 2. **"Subscribed" labels** highlight publications the user subscribes to, with significantly
>    higher click-through in Google's testing.
> 3. **"Highly Cited" badges** expanded to more results — rewards original reporting and citable
>    primary assets (calculators, data studies).
> 4. **In-text citation links** now sit next to the specific claims they support — rewards
>    claim-level citability; the statistic-block and definition-block structures align directly.

**Note (2026):** AI Mode launched broadly at Google I/O May 2025; 180+ countries by end-2025. In
Jan 2026 Gemini 3 became default for both AI Overviews and AI Mode, and citation-vs-top-10 overlap
collapsed from ~76% to ~38% — passage quality now outweighs raw ranking for inclusion. AI Overviews
cover ~26% of US searches; click-through to cited sources is ~1% (Pew Research 2025).

**Citation behavior**
- Inline hyperlinked citations woven into summary text; a collapsible Sources panel / carousel with
  domain favicons; AI Mode opens cited pages side-by-side on Chrome desktop (not a new tab).

**What gets cited**
- Listicles (~22%), articles (~17%), product pages (~14%); Reddit (~21%) and YouTube (~19%) are the
  top-cited single domains.
- Extractable *passages* — definitions, stats, stepwise how-tos, comparison tables, FAQ answers —
  not whole pages.
- Informational queries → articles; commercial queries → listicles.

**Content structure**
- Optimal extracted-passage length: **134–167 words**.
- ~44% of citations pulled from the first 30% of the page body — lead with the answer.
- Schema.org JSON-LD (FAQ, HowTo, Article, Product) aids selection; multimodal pages
  (text + image + video + schema) see higher selection rates.
- **`llms.txt` is NOT used by Google** — Gary Illyes confirmed "normal SEO works"; Danny Sullivan
  (Jan 2026) warned against chunking content specifically for LLMs.

**Authority signals**
- Entity authority, factual accuracy, and author credentials outweigh raw Domain Authority under
  Gemini 3. The Mar 2026 core update rewarded human-led expert content with bylines + verified
  author profiles and demoted scaled AI content. Interlinked topic clusters correlate with higher
  citation rates.

**Citation frequency:** ~13 sources per overview in 2026 (up from ~7 in 2024). 88% of overviews cite
3+ sources; long overviews (>6,600 chars) cite ~28.

**Notable 2024–2026 changes:** May 2025 AI Mode launch · Jul 2025 Pew (AIO cut click rates ~47%;
~1% of viewers click a cited source) · Nov 2025 global publisher Google traffic down ~33% YoY
(Chartbeat) · Jan 2026 Gemini 3 default, overlap 76%→38% · Mar 2026 core update re-emphasizes E-E-A-T.

*Verified Apr 2026 against blog.google, Search Engine Land, Pew Research, Press Gazette, CXL,
Profound. Vendor schema-uplift figures (~73% / 317%) are single-study claims — directionally
positive, exact magnitudes unproven.*

---

## ChatGPT / ChatGPT Search

> **UPDATE (verified 2026-07-16; sources: developers.openai.com/api/docs/bots; Search Engine Land
> Jul 1 & 8, 2026):**
> - **Multi-backend retrieval (reverse-engineered, unofficial):** a `result_source` field shows four
>   backends — "Labrador" (~88% of primary sources), Bright Data (~10%), Oxylabs, SERP. Retrieval is
>   non-deterministic: ~12% of repeated prompts switch backends, dropping URL overlap ~45%.
>   Single-snapshot citation checks are unreliable — audit across repeated runs.
> - **Thinking mode is a different citation surface:** vs Instant mode, only 25.6% domain overlap;
>   citation rate 50%→68%; ~24 sub-queries per comparison prompt vs ~5.5. Thinking mode shifts away
>   from Reddit/UGC (15%→7%) toward official docs (12.4%→17.5%) and gov/academic (1.9%→8.8%) — depth
>   and per-subtopic pages (pricing, integrations, FAQs as separate crawlable pages) win here.
> - **Crawler split (official):** `OAI-SearchBot` controls ChatGPT Search visibility; `GPTBot` is
>   training-only; `ChatGPT-User` is user-triggered fetches. Independent robots.txt controls — allow
>   OAI-SearchBot even if blocking GPTBot. ~24h propagation.
> - **Plain server-rendered HTML for prices/specs/facts:** ChatGPT visibly falls back to third-party
>   sources when first-party facts hide behind JS.

**Note (2026):** SearchGPT merged into ChatGPT as "ChatGPT Search" (Oct 2024); universally available
with no login since Feb 2025. ChatGPT triggers web search automatically per-query (~18% of
conversations). The Mar 2026 model transition (GPT-5.3 Instant default, GPT-5.4 Thinking premium)
cut cited web sources ~20% and sharply diverged citation preferences across models (~7% overlap).
ChatGPT Atlas (OpenAI's AI browser, Oct 2025) added a sidebar citation UI.

**Citation behavior**
- Inline numbered citations `[1]`, `[2]` woven into prose (no separate SERP-style list); hover-preview
  source cards on desktop, click-through on mobile; Atlas sidebar surfaces search/images/videos/news
  as separate tabs.

**What gets cited**
- Definitions using "X is / X refers to" phrasing — ~2× cited vs vague framing.
- Q&A structures — 78% of cited passages originate from H2/H3 headings; cited content ~2× more likely
  to contain a question mark.
- Entity-rich passages (~20% proper-noun density vs 5–8% typical English).
- First third of page ~44% of citations; middle ~31%; last third ~25%. GPT-5.4 Thinking prefers
  commercial/pricing pages (51% of citations).

**Source selection**
- **Referring-domain count gatekeeps retrieval** — sites with 32K+ RDs are ~3.5× more likely to be
  cited than sub-200-RD sites.
- Wikipedia ~5% of citations; Reddit ~3%. OpenAI licensing partners (Axel Springer, News Corp,
  Condé Nast, FT, Reuters, Axios, Dotdash Meredith) surface with explicit attribution. Third-party
  review profiles (Trustpilot/G2/Capterra/Yelp) → ~3× higher citation probability. Content updated
  in the last 30 days cited ~3.2× more.

**Quoting:** paraphrase with close lexical fidelity; direct SVO statements outperform hedged prose; no
systematic verbatim block quoting.

**Citation frequency:** ~10 sources per response; 15 unique domains / 19 unique URLs after the Mar
2026 transition (down from 19/24 before).

*Verified Apr 2026 against openai.com, help.openai.com, Search Engine Land, Digiday, Profound,
Writesonic, Dataconomy. Model names (GPT-5.3/5.4) are trade-press reporting, not a direct OpenAI
announcement — treat cautiously. Vendor schema/FAQ weighting figures (40%) are directional.*

---

## Perplexity AI

> **UPDATE (verified 2026-07-16; sources: docs.perplexity.ai crawlers page; Perplexity blog; Jun 2026
> funding coverage):**
> - **Two crawlers, independent controls:** `PerplexityBot` (search index, not training; publishes IP
>   JSON) and `Perplexity-User` (live per-query fetch; generally IGNORES robots.txt since
>   user-initiated). Perplexity's own docs warn WAFs (Cloudflare/AWS) are the common accidental-block
>   point — allowlist by UA AND published IP ranges, not just robots.txt.
> - **Selection mechanics:** ~10–30 candidates → BM25 + embedding rerank → cites 3–5. A direct answer
>   in the first 1–2 sentences of a section is the extractability lever. JS-only rendering widely
>   reported as a failure mode (unconfirmed by Perplexity docs).
> - **Comet Plus economics:** citations count toward publisher payout even WITHOUT click-through (80%
>   rev share, ~$42.5M initial pool; ~$200M raised Jun 2026 at $20B; Comet ~3M MAU Q1 2026). Being
>   cited now has direct monetization potential for qualifying publishers, independent of traffic.

**Note (2026):** Perplexity moved off external-model routing (GPT/Claude) to its in-house **Sonar**
family (Feb 2025, Llama 3.3 70B base, Cerebras-accelerated ~1,200 tok/sec), default for free and Pro.
**Comet** browser + publisher **revenue-share** launched Aug 2025 ($5/mo, 80/20 split, $42.5M pool).
**Spaces** replaced Pages. Sonar-Reasoning-Pro ties for #1 in Search Arena with Gemini-2.5-Pro-Grounding.

**Citation behavior**
- Numbered inline citations (superscript) clickable to source cards showing domain + title; **3–5
  inline citations per response** (standard UI pattern); source list in an expandable right-rail panel.

**What gets cited**
- Static HTML with schema markup — 94% parse success vs 23% for JS-rendered content.
- **Reddit is disproportionately represented** — 24% of all Perplexity citations (Jan 2026), ~6× more
  than YouTube.
- Stats with specific numbers + attribution — every citable passage needs claim + number/qualifier +
  source.

**Content structure**
- Direct answer in the first **40–60 words** of each section.
- **Atomic paragraphs** — each must stand alone without surrounding context (Sonar extracts
  paragraph-atomically).
- Question-based H2/H3 headers mirroring user queries; lists, bullets, tables; subheadings every
  200–300 words.

**Authority signals**
- **Freshness is the most aggressive signal** — updates boost citation rate ~37% in the first 48
  hours. Authority is a weak baseline (Google rank provides a trust floor but does NOT determine
  citation); lower-DA sites with better structure + recency routinely beat high-DA sites.

**Citation frequency:** **3–5 sources per response** (official Help Center). Perplexity visits ~10
pages per query and selects 3–4. Average 5.0 links per response vs ChatGPT's 10.4 and Google AIO's ~13.

**Focus modes:** Web (broad, freshness-weighted) · Academic (peer-reviewed only) · Reddit/Social
(explains the 24% Reddit share) · YouTube (transcript extraction; social citation share 19%→39%
Aug–Dec 2025) · News (recency-capped).

*Verified Apr 2026 against perplexity.ai blog + help center, Axios, Search Engine Journal, TechCrunch,
erlin.ai, Wellows, PikaSEO. Vendor uplift figures (150% from question-format headers, 45% from
schema) are directional, not independently replicated.*

---

## Claude (hybrid: training + live web access)

> **UPDATE (verified 2026-07-16; sources: platform.claude.com web-search docs; ppc.land Feb 25, 2026):**
> - **Three crawlers, independent (Anthropic docs, Feb 2026):** `ClaudeBot` (training) ·
>   `Claude-SearchBot` (search index) · `Claude-User` (live user-directed fetch). Block training while
>   staying visible in answers by allowing the latter two. Anthropic publishes NO stable IP ranges —
>   robots.txt UA rules are the only supported control (unlike OpenAI/Perplexity).
> - **Dynamic Filtering (web_search_20260209, Feb 2026):** Claude code-filters raw search results
>   BEFORE they enter context — structured, cleanly-parsed pages are likelier to survive the filter
>   pass (inference, not Anthropic-stated).
> - **llms.txt:** Anthropic maintains one for its own docs, but there is NO public confirmation
>   Claude's retrieval prioritizes third-party `llms.txt` when citing. Treat as unproven for Claude.
> - No published ranking-factor list exists for Claude — a genuine gap vs Google/OpenAI. Behavior
>   appeared stable Mar–Jul 2026 while ChatGPT/Perplexity pipelines visibly shifted.

**Note (2026):** Claude is a hybrid citation surface, not training-only. `claude.ai` has native web
search with inline source links (launched Mar 2025 paid-US, global May 2025). The API's `web_search`
tool (launched May 7 2025; version `web_search_20260209`) auto-attaches citation objects
(`url` + `cited_text`) to every text block sourced from search. Knowledge cutoffs vary by model; live
fetch fills the gap.

**Citation behavior**
- Inline links / brackets at the point of claim on claude.ai — **no** Perplexity-style footer list.
  The API `web_search` returns structured citation objects (url + cited_text) per sourced text block.

**What gets cited**
- Training-era: high-authority reference corpora (Wikipedia, major news, academic publishers, official
  docs) surface as uncited factual recall unless web search is invoked.
- Live-fetch: whatever `web_search` returns for the model-generated query — documentation sites, blogs,
  product pages, news; anything crawlable and indexed.

**Content structure**
- Clean HTML → Markdown conversion aids extraction; semantic HTML + schema.org JSON-LD help (inferred
  from the conversion pipeline; no Anthropic statement).
- `llms.txt`: Anthropic publishes one for its own docs but has **NOT confirmed** consumption by
  Claude's crawlers. Multiple 2025 audits show no major AI system requests `llms.txt` for retrieval.
  Treat as aspirational convention, not required.

**Authority signals**
- No published ranking algorithm for `web_search`; inferred standard web-authority signals (backlinks,
  domain age, HTTPS, freshness) flow through the upstream index. YMYL (medical, legal) content receives
  conservative treatment.

**Citation frequency:** 2–6 inline citations per claude.ai web-search response; the API returns one
citation per cited span, often 3–10 across a long answer.

**Crawler opt-out:** `robots.txt` with `User-agent: ClaudeBot` / `Claude-User` / `Claude-SearchBot` →
`Disallow: /` (list all three). IP blocking is discouraged (it also blocks robots.txt reads). Legacy
UAs `anthropic-ai` / `Claude-Web` appear in older directories but are not on Anthropic's current list.

*Verified Apr 2026 against anthropic.com, support.claude.com, claude.com/blog, TechCrunch, Search
Engine Land, InfoQ, Ahrefs. `llms.txt` consumption by Claude's live-fetch crawlers is DISPUTED — treat
cautiously.*

---

## Google Gemini app (added 2026-07-16)

**Architecture** (verified 2026-07-16; ai.google.dev/gemini-api/docs/google-search updated 2026-07-06):
the Gemini app cites via **Grounding with Google Search** — the model decides per turn whether to
search, fires one or more queries (multi-query fan-out is standard on Gemini 3.x), and returns inline
`url_citation` spans mapping claims to URLs. Same grounding stack as AI Overviews/AI Mode; only the
surface differs.

- **No separate Gemini crawler exists.** Googlebot indexability IS Gemini visibility (Google-Extended
  only controls training opt-out). Optimizing for Gemini = Google Search technical health + the AI
  Overviews playbook above; the distinctive ~20% is multimodal queries and multi-turn follow-ups.
- **Google explicitly ignores `llms.txt`** (developer guidance Jun 16 & 29, 2026): no AI files,
  markup, or Markdown needed — "won't harm (nor help)."
- **Citation share skews hard to platforms** (Ahrefs Brand Radar, ~3M queries, Jun 2026, directional):
  Reddit ~27.5%, YouTube ~13.7%, Wikipedia ~12.7% — ~54% combined.
- Scale: 900M+ monthly Gemini users (Google I/O, May 19 2026).

**Tactics:** keep every money page server-rendered and Googlebot-clean; maintain accurate entity/schema
signals (knowledge-graph presence matters more on a conversational surface that shows fewer links);
seed Reddit/YouTube/Wikipedia presence for brand queries; structure content to survive follow-up
questioning (edge cases, exceptions, "when this doesn't apply" blocks).

---

## Common traits across all AI systems

- **Content quality:** factual accuracy (incorrect info won't be cited), clear unambiguous language,
  proper grammar, comprehensive coverage, up-to-date information.
- **Structure:** scannable format (headings, lists, tables), logical organization, clear topic
  segmentation, short paragraphs, visual hierarchy.
- **Authority:** domain credibility, author credentials, source citations *in* the content, expertise
  signals, editorial quality.
- **Relevance:** precise match to query intent, topic focus, keyword-topic alignment, depth on the
  specific topic.

---

## Content optimization by query type

**Informational ("What is…", "How does…", "Why…")** — clear definitions, comprehensive explanations,
expert perspectives, supporting statistics, real-world examples. Lead with a definition; then "why it
matters," how it works, common use cases, expert citations.

**Comparison ("[A] vs [B]", "Best [category]")** — comparison tables, clear pros/cons, use-case
recommendations, specific differentiators, a verdict. Put a quick comparison table upfront, then
feature-by-feature detail and "choose X if…" guidance.

**How-to ("How to…", "Steps to…")** — numbered step-by-step processes, prerequisites/tools, time
estimates, success indicators, troubleshooting. List prerequisites first, then clear numbered steps
and common problems.

**Statistical ("How much…", "How many…", "Statistics about…")** — specific numbers with sources,
recent data (within 1–2 years), multiple data points, context, trends. Lead with the key statistic,
attribute immediately, then interpret.

---

## Citation likelihood factors

**High likelihood**
- Recognized authority domains (high referring-domain count)
- Published/updated within 6 months (30-day freshness boosts ChatGPT citations 3.2× and Perplexity
  37% in the first 48h)
- Clear, standalone statements (atomic paragraphs that parse without surrounding context)
- Proper source attribution; specific statistics with dates
- Structured with headings/lists/tables + schema.org JSON-LD; interlinked topic clusters
- Author credentials visible (bylines + verified author profiles — post Mar 2026 Google core update)
- Technical accuracy verified; consensus with other sources

**Medium likelihood**
- Less-known but quality domains; published 6–18 months ago; clear but needs slight context; general
  industry claims; good but less-scannable structure; moderate depth; no author but quality content.

**Low likelihood**
- Unknown / low-authority domains; published 18+ months ago without updates; vague statements; no
  sources; walls of text; thin coverage; promotional tone; factual inconsistencies; no expertise
  signals; JS-rendered content without SSR fallback (Perplexity parses 23% vs 94% for static HTML);
  scaled AI content without human bylines (demoted in the Mar 2026 Google core update).

---

## AI system comparison summary

| Factor | Google AI Overviews / AI Mode | ChatGPT / ChatGPT Search | Perplexity (Sonar) | Claude (web-search mode) |
| --- | --- | --- | --- | --- |
| **Freshness bias** | High | High (30-day 3.2× boost) | Very high (48h 37% boost) | Medium (query-dependent) |
| **Authority weight** | Entity > DA (post Gemini 3) | Referring-domain count | Structure > DA | Standard web-auth (inferred) |
| **Structure importance** | High (schema; 134–167w passages) | High (H2/H3; SVO definitions) | Very high (atomic paragraphs) | Medium (semantic HTML) |
| **Citation count (2026 avg)** | ~13 | ~10 | 3–5 | 2–6 |
| **Quotable focus** | High | High (direct SVO) | Very high | Medium |
| **Domain trust** | Entity authority | Licensed partners + RDs | Reddit prominent | Undocumented |
| **`llms.txt`** | Not used (Illyes confirmed) | Not consumed | Not consumed | Published but not confirmed consumed |
| **Typical citation format** | Inline links + Sources panel | Inline `[1]` + hover cards | Superscript + source cards | Inline links (no footer list) |

---

## Tracking AI citations

**Manual monitoring** — check whether your content appears in Google AI Overviews for target
keywords, ChatGPT responses (search your domain), Perplexity results, and Claude responses (test
specific queries with web search enabled). Test with exact-match FAQ questions, definitions of terms
you've defined, statistics you've cited with attribution, and processes you've documented.

**Indicators of AI visibility** — increased direct traffic (AI users clicking sources, though AIO CTR
is ~1%), traffic spikes from unusual referrers, low bounce / high time-on-page, return visitors, and
server-log hits for `ClaudeBot`, `Claude-User`, `Claude-SearchBot`, `OAI-SearchBot`, `GPTBot`,
`PerplexityBot`, `Google-Extended`.

---

## Optimization checklist

- [ ] At least 3 clear, quotable definitions (SVO, "X is / X refers to" phrasing)
- [ ] 5+ specific statistics with sources and dates
- [ ] Q&A sections covering top queries (78% of ChatGPT citations come from H2/H3 headings)
- [ ] Comparison tables where relevant; numbered lists for processes
- [ ] Published/updated within 6 months (prefer a 30-day window for freshness-biased surfaces)
- [ ] Author credentials visible (bylines + verified author profiles)
- [ ] External citations to authoritative sources
- [ ] Clear H2/H3 headings (question-format for Perplexity)
- [ ] Short paragraphs (2–4 sentences); atomic paragraphs that stand alone
- [ ] Optimal passage length 134–167 words (Google AIO)
- [ ] Schema.org JSON-LD (FAQ, HowTo, Article, Product)
- [ ] Static HTML (avoid JS-only rendering — Perplexity parses 94% vs 23%)
- [ ] `robots.txt` permits the AI crawlers you want citing you (`ClaudeBot`, `Claude-User`,
      `Claude-SearchBot`, `GPTBot`, `OAI-SearchBot`, `PerplexityBot`, `Google-Extended`)
- [ ] Optional: `llms.txt` at the domain root — but note: Google states its systems **ignore** it
      (developer guidance Jun 16/29 2026), there is no confirmed third-party consumption by Claude,
      and server-log studies show ~97% of `llms.txt` files receive zero AI requests. Cheap
      agent-readiness hygiene, **not** a rankings or citation lever on any platform.

## Related

- [midnight-seo-skills](https://github.com/abouchard11/midnight-seo-skills) — the Claude Code skill suite I run my SEO portfolio with; this research is its GEO companion piece.

---

*Researched, verified, and maintained by Alex Bouchard ([MidnightDev](https://midnightdev.dev)).
Corrections may be reported by issue with a primary source. External code or content submissions require separate written terms.

## Rights

**Proprietary — all rights reserved. No license is granted.** See [LICENSE](LICENSE).
