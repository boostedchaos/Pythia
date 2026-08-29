# Feed verification — Phase 0.5 (Lane F)

Every source below was called for real from this machine before any adapter was
written. A source named in `PYTHIA-MONITOR-V1-PLAN.md` §8 is a **candidate**; what
makes it a fact is a recorded response, and that response is the fixture the parser
is written against.

**All calls made 2026-08-28** (machine local time; UTC stamps where they matter).
Fixtures live in `tests/fixtures/`, trimmed where noted — trimming removes items,
never fields, so every parsed field is a real one.

**Adopted: 9.  Rejected: 5.  Verified but held in reserve: 2.**

> Those tallies are Phase 0.5's. **Phase 1 (2026-08-29) took the registry from 9 to 13**,
> and **Phase 1b (2026-08-29) added `fred`, 13 to 14**, closing the markets gap recorded
> below — see [Phase 1](#phase-1--2026-08-29) and [Phase 1b](#phase-1b--fred-2026-08-29-the-markets-gap-closed)
> at the end of this file for their own evidence and tallies.

| Beat | Adopted sources | Kind |
|---|---|---|
| ai | `arxiv`, `openai_news` | stream |
| cybersecurity | `cisa_kev` | snapshot |
| politics | `gdelt`, `state_dept_advisories` | stream, snapshot |
| healthcare | `federal_register`, `openfda` | stream |
| markets | `coingecko`, `treasury_yields` | snapshot |

A live end-to-end run of all nine against the real network (not fixtures) is at the
bottom of this file.

---

## arxiv

- **Called:** `http://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.LG&sortBy=submittedDate&sortOrder=descending&max_results=25`
- **Result:** HTTP 200, `application/atom+xml`, 64,663 bytes, 0.60 s.
- **Key:** none.
- **Terms / rate limits:** <https://info.arxiv.org/help/api/tou.html> — metadata is
  offered under CC0 1.0; the page asks for "no more than one request every three
  seconds" from a single connection. A half-hourly poll is far inside that.
- **Fixture:** `tests/fixtures/arxiv.xml` — the real feed trimmed from 25 entries to 3.
- **Verdict: ADOPTED.**
- **Note on identity:** arXiv ids carry a version suffix (`2608.27454v1`). The
  adapter strips it, so a v2 revision is a *change to the same paper* rather than a
  new observation.

## openai_news

- **Called:** `https://openai.com/news/rss.xml`
- **Result:** HTTP 200, `text/xml`, 703,540 bytes, 0.22 s, 1,157 `<item>` elements.
- **Key:** none. Public RSS.
- **Fixture:** `tests/fixtures/openai_news.xml` — trimmed from 1,157 items to 3.
- **Verdict: ADOPTED** as the AI vendor release feed. The adapter reads only the
  first 30 items; a monitor wants the head of the feed, not its whole archive.

## anthropic_news — REJECTED

- **Called:** `https://www.anthropic.com/news/rss.xml`
- **Result:** **HTTP 404**, `text/html`, 60,050 bytes (a Next.js error page).
- **Verdict: REJECTED** — the RSS path named as a candidate in the build brief does
  not exist. Replaced by `openai_news`, which verified.

## huggingface_blog — verified, held in reserve

- **Called:** `https://huggingface.co/blog/feed.xml`
- **Result:** HTTP 200, `application/rss+xml`, 251,388 bytes, 0.24 s.
- **Verdict: NOT ADOPTED.** It works and it is keyless; the AI beat's two-source
  minimum is already met by arXiv plus OpenAI. Recorded here so that swapping it in
  needs no fresh investigation — it is the same RSS shape `openai_news.py` parses.

## cisa_kev

- **Called:** `https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json`
- **Result:** HTTP 200, `application/json`, 1,618,253 bytes, 0.55 s. Catalog version
  `2026.08.27`, `count: 1685`.
- **Key:** none. US federal government work; public domain.
- **Fixture:** `tests/fixtures/cisa_kev.json` — trimmed from 1,685 vulnerabilities to
  3. The `count` field is left at its real value of 1685, so the fixture does not
  pretend the catalog is small.
- **Verdict: ADOPTED.** `KIND = "snapshot"`, per the contract: the whole catalog
  arrives each fetch, so a CVE leaving it is meaningful.
- **Note on url:** KEV rows carry no link of their own. The canonical url is
  `https://nvd.nist.gov/vuln/detail/<cveID>`, derived from the id — deterministic,
  not invented per-fetch.

## gdelt — ADOPTED, with a live TLS problem

- **Called (HTTPS):** `https://api.gdeltproject.org/api/v2/doc/doc?query=…&mode=artlist&format=json&timespan=1d`
- **Result:** **connection failed** — `SSL: CERTIFICATE_VERIFY_FAILED, certificate has
  expired`. This is upstream, not local:

  ```
  subject= /CN=*.gdeltproject.org
  issuer=  /C=US/O=Let's Encrypt/CN=YR2
  notBefore=May 30 19:50:13 2026 GMT
  notAfter= Aug 28 19:50:12 2026 GMT
  ```

  The wildcard certificate expired at **2026-08-28T19:50:12Z**, about six hours
  before these checks (2026-08-29T01:58:57Z).

- **Called (HTTP, to test the API itself):** the same query over `http://` returned
  **HTTP 200** with valid articles, so the **API is healthy and only the TLS
  certificate is broken**.
- **Key:** none. GDELT publishes under CC0 1.0 (<https://www.gdeltproject.org/about.html>).
- **Fixture:** `tests/fixtures/gdelt.json` — the real HTTP-variant response, 5 articles.
- **Verdict: ADOPTED over HTTPS.** We deliberately did **not** downgrade the adapter
  to plain HTTP to make it green. An unauthenticated plaintext feed can be modified
  in transit, and its contents are quoted in a brief; a source that fails loudly is
  better than one that can be edited by the network. Until the certificate is
  renewed, `gdelt.fetch()` returns `status="error"` and the other seven adapters are
  unaffected.
- **Recheck (one line, no code change needed once it passes):**

  ```
  curl -sS -o /dev/null -w '%{http_code}\n' --max-time 15 \
    'https://api.gdeltproject.org/api/v2/doc/doc?query=test&mode=artlist&format=json&maxrecords=1'
  ```

  `200` means the adapter starts working on its next poll. **This is the one thing in
  this lane that is not currently serving data — it needs a decision if it does not
  clear within a day or two** (accept plaintext, or find a politics source that does
  not have this problem).

## reliefweb — REJECTED (needs a pre-approved appname)

Requested by the team lead 2026-08-28 as a keyless candidate for the politics beat.
It is not keyless.

- **Called (as briefed):** `https://api.reliefweb.int/v1/reports?limit=3`
- **Result:** **HTTP 410 Gone** — `{"status":410,"error":{"message":"The API version
  'v1' has been decommissioned. Please use version 'v2' instead."}}`. The v1 URL in
  the brief no longer exists.
- **Called (v2, following the API's own instruction):**
  `https://api.reliefweb.int/v2/reports?appname=pythia-monitor&limit=3`
- **Result:** **HTTP 403 AccessDeniedHttpException** — "You are not using an approved
  appname. Kindly request an appname from ReliefWeb here:
  https://apidoc.reliefweb.int/parameters#appname".
- **Terms:** <https://apidoc.reliefweb.int/parameters> — the `appname` parameter is
  **Mandatory**, and: "From 1 November 2025, API users will require a **pre-approved
  appname**. Request an appname by completing this short form … ReliefWeb will review
  your request and send you an email."
- **Verdict: REJECTED.** A human registration step plus an email approval is a
  credential in everything but name. The lane brief scoped keyed sources out, and the
  lead confirmed not to adopt any. Adoptable later if someone completes the form.

## un_news — REJECTED (robots.txt)

The lane brief's named fallback. It serves fine; it is the robots rules that stop it.

- **Called:** `https://news.un.org/feed/subscribe/en/news/all/rss.xml`
- **Result:** **HTTP 200**, `application/rss+xml`, 34,098 bytes, 0.18 s, 30 items.
  Well-formed, and `<guid isPermaLink="true">` carries the canonical article URL while
  `<link>` carries a `/feed/view/` variant — the guid would have been the right url.
- **Terms — the reason it is rejected.** In `https://news.un.org/robots.txt`:
  - `User-agent: *` opens at **line 16** and runs to line 135.
  - **Line 98: `Disallow: */news/`** — inside that general group. Our feed path
    `/feed/subscribe/en/news/all/rss.xml` contains `/news/`, so it matches.
  - **Lines 136-137** grant `User-agent: Feedfetcher-Google` an explicit
    `Allow: /feed/subscribe/` — the site clearly considered feed fetching and scoped
    the permission to one named agent, which we are not.
- **Verdict: REJECTED.** Under a literal reading — which is how robots.txt is actually
  evaluated — a generic agent is disallowed from this URL. The narrow named-agent
  Allow makes it hard to argue the general group was meant to permit us too.
  **This is a judgement call and it is reversible:** if the lead reads it the other
  way, the adapter is a near-copy of `openai_news.py` (RSS, guid as url) and can be
  written in minutes. Nothing else about the source is problematic.

## state_dept_advisories — ADOPTED (the substitute for both)

With ReliefWeb and UN News both out, politics would have had **zero** live sources
(GDELT being dark). Plan §8 asks for "humanitarian and **official advisory** sources";
this is the official-advisory half, and it verified cleanly.

- **Called:** `https://travel.state.gov/_res/rss/TAsTWs.xml`
- **Result:** **HTTP 200**, `text/xml`, 916,938 bytes, **220 `<item>` elements** — one
  travel advisory per country. Re-fetched three times: 200 every time.
- **Key:** none. US federal government work; public domain.
- **Fixture:** `tests/fixtures/state_dept_advisories.xml` — trimmed from 220 items to
  4, deliberately choosing **one item at each advisory level (1, 2, 3, 4)** so the
  level-extraction test exercises the whole range rather than one example.
- **Verdict: ADOPTED.**
- **`KIND = "snapshot"`, a deliberate deviation from the `"stream"` the lead specified**
  for the ReliefWeb adapter. The contract defines snapshot as "full current state each
  fetch; GONE is meaningful", and this feed carries an advisory for *every* country on
  every fetch. A country dropping out is real information, so snapshot is the honest
  classification for this source. Flagged rather than silently applied.
- **The advisory LEVEL is the value.** A country moving Level 2 -> Level 4 is exactly
  the kind of change the brief exists to surface, so it is parsed out of the title
  (`"Qatar - Level 3: Reconsider Travel"`) into `extra["advisory_level"]` as an int,
  with the wording in `extra["advisory_label"]`. Live level spread on 2026-08-28:
  **Level 1: 86, Level 2: 83, Level 3: 28, Level 4: 22** (219 accepted).
- **Identity** is `dc:identifier` (e.g. `"QA,advisory"`), not the url. The advisory url
  is permanent while the level changes, so keying on the identifier makes an
  escalation a *change to the existing observation* rather than a new one. Guarded by
  `test_state_dept_identity_survives_a_level_change`.
- **Two real parsing traps found by calling it, both now guarded:**
  1. **`pubDate` carries no time** — `"Fri, 28 Aug 2026"`. `email.utils.parsedate_to_datetime`
     rejects that form, so a naive RFC-822 parse would have lost **every** timestamp in
     the feed. The adapter falls back to a date-only parse; live run has 0 missing
     timestamps across 219 items.
  2. **The exception type is Python-version dependent** — 3.9 raises `TypeError`,
     3.13 (what `uv` runs here) raises `ValueError`. The adapter catches both, and the
     test asserts the *rejection* rather than the type, so it cannot break on an
     interpreter upgrade.
- **Descriptions are CDATA HTML** and are tag-stripped into plain prose for the brief.

## federal_register

- **Called:** `https://www.federalregister.gov/api/v1/documents.json?per_page=20&order=newest` with
  `conditions[agencies][]=health-and-human-services-department`,
  `…=centers-for-medicare-medicaid-services`, `…=food-and-drug-administration`, and
  an explicit `fields[]` list.
- **Result:** HTTP 200, `application/json`, 32,001 bytes, 0.31 s. Response description:
  "Documents from Health and Human Services Department, Centers for Medicare &
  Medicaid Services, and Food and Drug Administration."
- **Key:** none. US federal government work; public domain.
- **Fixture:** `tests/fixtures/federal_register.json` — trimmed to 5 results.
- **Verdict: ADOPTED.** The live adapter requests `per_page=40`.
- **Document type**, which plan §8 calls "most of the value", is carried in
  `extra["doc_type"]`, mapped from the API's own `type` field:
  `Proposed Rule → proposed_rule`, `Rule → final_rule`, `Notice → notice`,
  `Presidential Document → presidential`. An unrecognised type is passed through
  lowercased, never silently relabelled a notice. The raw value is kept alongside in
  `extra["raw_type"]` so the mapping is always auditable.

## openfda

- **Called (first attempt):** `https://api.fda.gov/drug/enforcement.json?limit=5` —
  HTTP 200, but the default sort returned a **recall from 2016**. Rejected as a query,
  not as a source.
- **Called (adopted):** `https://api.fda.gov/drug/enforcement.json?sort=report_date%3Adesc&limit=25`
  — HTTP 200, 31,410 bytes, newest records `report_date 20260819`, Class I and II,
  status "Ongoing".
- **Key:** **not required.** <https://open.fda.gov/apis/authentication/> states the
  keyless limits as **240 requests per minute and 1,000 per day, per IP address**. A
  half-hourly poll is 48 calls a day, well inside the keyless tier, so no key is
  stored anywhere.
- **Fixture:** `tests/fixtures/openfda.json` — 5 recent records plus one specific real
  record described below.
- **Verdict: ADOPTED.**
- **Defect found by the live run, now fixed and guarded:** openFDA records do **not**
  all carry a `recall_number`. A real **Class I** recall from Baxter Healthcare
  (`event_id` 99463, Cefazolin in Dextrose injection) had an empty one, and the first
  version of the adapter silently dropped it — 25 received, 24 accepted. Identity now
  falls back to `event_id`. That exact record is in the fixture and
  `test_openfda_keeps_records_that_have_no_recall_number` fails without the fallback.
- **Note on url:** openFDA records have no public web page, so the canonical url is a
  query for that record — `…/drug/enforcement.json?search=recall_number:%22D-0769-2026%22`
  — deterministic and resolvable. The quotes are percent-encoded; a bare `"` is not
  valid in a URL.

## coingecko

- **Called:** `https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,pax-gold&vs_currencies=usd&include_24hr_change=true&include_last_updated_at=true`
- **Result:** HTTP 200, `application/json`. Response headers carried
  `cache-control: max-age=30` and **no `x-ratelimit-*` headers**.
- **Key:** none for this endpoint.
- **Rate limit: TODO — not verified.** The documented per-minute limit for the keyless
  public tier could not be read: <https://docs.coingecko.com/docs/rate-limits> renders
  its content client-side and returned no limit text to a plain fetch, and the API
  exposes no rate-limit headers. No number is asserted here rather than one being
  guessed. The planned cadence (one call per poll) is low enough that this is a
  documentation gap, not an operational risk, but it should be confirmed before the
  poll interval is ever shortened.
- **Fixture:** `tests/fixtures/coingecko.json` — the full real response, untrimmed.
- **Verdict: ADOPTED.** `KIND = "snapshot"`.
- **Identity (plan §5.11):** `upstream_id` is the **symbol** (`BTC`, `ETH`, `PAXG`).
  The price appears only in `extra["price"]`, and the title carries no number, so a
  moving quote cannot manufacture a new observation. Guarded by
  `test_market_price_is_never_part_of_identity`, which refetches the same instruments
  at different prices and asserts identity is unchanged.
- **Honest labelling:** **PAXG is a gold-backed token used as a gold PROXY, not a gold
  fixing.** It is tagged `extra["instrument_kind"] = "gold_proxy"` and its title says
  "gold proxy", so a brief cannot present it as the spot gold price.

## treasury_yields

- **Called:** `https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value_month=202608`
- **Result:** HTTP 200, `text/xml`, 31,573 bytes — an OData Atom feed, one entry per
  publication date, each carrying the full par yield curve (`BC_1MONTH` … `BC_30YEAR`).
- **Key:** none. US federal government work; public domain.
- **Fixture:** `tests/fixtures/treasury_yields.xml` — trimmed to 3 dated entries, which
  is what lets the test prove the adapter takes the **newest** one rather than the first.
- **Verdict: ADOPTED.** `KIND = "snapshot"`; instruments `UST3M`, `UST2Y`, `UST10Y`,
  `UST30Y`; the yield is in `extra["price"]` with `unit: percent_per_annum`, never in
  the identity.
- **Month-boundary handling:** the current-month feed exists but holds no entry before
  the month's first publication, so the adapter falls back to the previous month
  rather than reporting an empty curve on the 1st.

## stooq — REJECTED

- **Called:** `https://stooq.com/q/l/?s=^spx,^dji,^ndq,xauusd,btcusd&f=sd2t2ohlcv&h&e=csv`
  and five further variants: single symbol, unencoded `^`, `?s=spx` with no caret,
  `?s=btcusd&e=csv`, the `/q/d/l/` daily endpoint, and the `stooq.pl` domain.
- **Result:** **HTTP 404 on every CSV variant**, serving an HTML "The page you
  requested does not exist" page, both with a default curl user-agent and with a
  browser user-agent. The site root returned 200 but only 796 bytes.
- **Verdict: REJECTED** — not reachable from this network. Since the target host
  (VM 107, 192.168.0.28) is on the same network, this is expected to fail there too.

## yahoo finance — REJECTED

- **Called:** `https://query1.finance.yahoo.com/v8/finance/chart/^GSPC?interval=1d&range=5d`
  and the same path on `query2`, with a browser user-agent.
- **Result:** **HTTP 429 Too Many Requests** on both, on first contact.
- **Verdict: REJECTED** on two independent grounds: it does not serve us, and it is an
  undocumented endpoint whose automated use Yahoo's terms do not permit. Not adopted
  even if the 429 clears.

## frankfurter — verified, not adopted

- **Called:** `https://api.frankfurter.dev/v1/latest?base=USD&symbols=EUR,JPY,GBP`
- **Result:** HTTP 200 — `{"amount":1.0,"base":"USD","date":"2026-08-28","rates":{"EUR":0.85889,"GBP":0.73624,"JPY":159.68}}`
- **Verdict: NOT ADOPTED.** Keyless and healthy, but ECB reference FX adds a beat
  dimension nobody asked for. Recorded as the ready option if FX is ever wanted.

---

## Known coverage gap — markets

Plan §8 asks for "major indices, rates/treasury yields, oil, gold, BTC". What is
actually served, and what is not:

| Instrument | Status |
|---|---|
| BTC, ETH | covered — `coingecko` |
| Gold | **proxy only** — PAXG, a gold-backed token, explicitly labelled as a proxy |
| Treasury yields (3M, 2Y, 10Y, 30Y) | covered — `treasury_yields` |
| Major equity indices (S&P 500, Dow, Nasdaq) | **NOT COVERED** — *closed 2026-08-29 by `fred`, see Phase 1b* |
| Oil | **NOT COVERED** — *closed 2026-08-29 by `fred`, see Phase 1b* |

No keyless source for equity indices or oil survived verification: Stooq 404s from
this network and Yahoo returns 429 and is ToS-hostile. Every remaining candidate
known to us (FRED, Alpha Vantage, Twelve Data, EIA, Nasdaq Data Link) requires an API
key, which the build brief scoped out. **This is a real gap, not an oversight, and it
needs a decision:** register a free key for one of them (FRED covers indices, oil and
gold from one keyed source), or accept crypto-plus-rates as the markets beat for v1.

---

## Live end-to-end run

All eight adapters run against the **real network**, not fixtures
(`uv run python` over `engine.monitor.adapters.ADAPTERS`, 2026-08-28):

```
arxiv                  ai             healthy  http=200  recv=   25 acc=   25
openai_news            ai             healthy  http=200  recv= 1157 acc=   30
cisa_kev               cybersecurity  healthy  http=200  recv= 1685 acc= 1685
gdelt                  politics       error    http=None recv=    0 acc=    0
                       ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate has expired
state_dept_advisories  politics       healthy  http=200  recv=  219 acc=  219
federal_register       healthcare     healthy  http=200  recv=   40 acc=   40
openfda                healthcare     healthy  http=200  recv=   25 acc=   25
coingecko              markets        healthy  http=200  recv=    3 acc=    3
treasury_yields        markets        healthy  http=200  recv=    4 acc=    4
```

**Eight of nine healthy against live endpoints, and every beat now has at least one
source actually serving data.** GDELT fails exactly as designed: a clean
`status="error"` with a safe message, no exception escaping, no effect on the other
eight. Politics is covered by `state_dept_advisories` while GDELT's certificate is
broken, so the brief can speak to all five beats honestly today.

---

# Phase 1 — 2026-08-29

Second pass, same discipline: one real HTTP call **before** any adapter was written, the
recorded response becomes the fixture, terms and robots checked, and a candidate that
fails verification is written down and replaced rather than quietly adopted.

**All calls made 2026-08-29** (UTC stamps where they matter).

**Adopted: 4 (registry 9 → 13).  Rejected: 3.  Rechecked, unchanged: 1 (GDELT).**

| Beat | Added | Kind | Beat now has |
|---|---|---|---|
| ai | `huggingface_blog` | stream | 3 |
| cybersecurity | `cisa_advisories` | stream | 2 |
| politics | `un_press` | stream | 3 (2 serving; GDELT still dark) |
| markets | `frankfurter` | snapshot | 3 |

Registry count is asserted, not assumed —
`uv run python -c "from engine.monitor.adapters import ADAPTERS; print(len(ADAPTERS))"`
returned **9 before** and **13 after**.

## cisa_advisories — ADOPTED

- **Called:** `https://www.cisa.gov/cybersecurity-advisories/all.xml`
- **Result:** HTTP 200, `application/rss+xml`, 481,093 bytes, 0.25 s, **30 `<item>`**.
- **Key:** none. US federal government work; public domain.
- **robots.txt** (`https://www.cisa.gov/robots.txt`, 80 lines): one `User-agent: *` group
  at line 16 disallowing only `/core/`, `/profiles/`, assorted READMEs, `/admin/`,
  `/comment/reply/`, `/filter/tips`, `/node/add/`, `/search/`, `/search?`,
  `/user/register`. A second group at line 80 blocks **PetalBot** only. Neither
  `/cybersecurity-advisories/` nor `/news-events/` is disallowed.
- **Fixture:** `tests/fixtures/cisa_advisories.xml` — trimmed from 30 items to 4,
  deliberately **one of each shape the feed carries**: an ICS advisory, an AA-series joint
  advisory, a KEV-catalog alert, and a revised advisory titled "(Update D)", so the
  classifier and the revision test exercise the real range rather than one example.
- **Verdict: ADOPTED.** `KIND = "stream"`.
- **It complements `cisa_kev` rather than duplicating it.** KEV is the machine-readable
  catalog of CVEs confirmed exploited; this is CISA's written analyst output. Composition
  of the live 30: **ICS advisories 18, alerts 9, AA-series joint advisories 2, resource 1.**
- **The overlap is real and is recorded rather than hidden:** 9 of the 30 items are
  "CISA Adds N Known Exploited Vulnerabilities to Catalog" alerts, which restate KEV
  activity. They are **kept**, because filtering them would need a title-sniffing rule that
  would eventually swallow a genuine alert. Instead every row is classified structurally in
  `extra["advisory_type"]` (`ics_advisory` / `joint_advisory` / `alert` / `other`) from the
  URL section, so a consumer can separate them without parsing wording. The raw section is
  kept alongside in `extra["raw_section"]` so the mapping stays auditable.
- **Identity is the advisory id, not the title.** An advisory reissued as "(Update D)" keeps
  its id and its URL while its title changes, so a revision is a **change to the same
  observation**. Alert URLs are dated slugs carrying no advisory id, so those fall back to
  URL identity (`upstream_id is None`). Both halves are guarded by
  `test_cisa_advisories_classifies_by_url_not_by_wording` and
  `test_cisa_advisory_identity_survives_a_revision`.
- **Parsing trap checked, not assumed: the feed stamps a TWO-DIGIT year** —
  `"Thu, 27 Aug 26 12:00:00 +0000"`. `email.utils.parsedate_to_datetime` reads this
  correctly per RFC 2822 (00–49 → 2000s, so 26 → 2026); verified against **all 10 distinct
  pubDate values** in the live feed, every one parsing to 2026. It is guarded anyway by
  `test_cisa_advisories_reads_the_feeds_two_digit_year`, because a regression here would
  shift every timestamp by ~2000 years while failing nothing else. Live run: **0 of 30
  observations missing a timestamp.**
- **Descriptions are escaped HTML** (CVSS tables and all) and are tag-stripped to prose.

## cisa ics-advisories.xml — REJECTED (redundant subset)

- **Called:** `https://www.cisa.gov/cybersecurity-advisories/ics-advisories.xml`
- **Result:** HTTP 200, `application/rss+xml`, 492,408 bytes, 30 items — **all 30 are ICS
  advisories**, 19 of which already appear in `all.xml`.
- **Verdict: REJECTED.** It adds only more of the beat's *lowest*-signal category while
  carrying none of the AA-series joint advisories or alerts. `all.xml` is the strictly
  better single feed. Recorded so nobody re-researches it.

## msrc (Microsoft Security Update Guide) — REJECTED (volume without exploitation signal)

The lane brief's optional vendor-advisory candidate. It verifies; it is rejected on the
brief's own stated criterion.

- **Called:** `https://api.msrc.microsoft.com/update-guide/rss`
- **Result:** HTTP 200, `application/rss+xml`, 2,446,259 bytes, **4,681 `<item>` elements**,
  one per CVE (`<guid>CVE-2026-70331</guid>`, `<category>CVE</category>`). Keyless.
- **Also called:** `https://api.msrc.microsoft.com/cvrf/v3.0/updates` — HTTP 200 JSON, and
  `https://msrc.microsoft.com/blog/feed/` — HTTP 200 but serves **HTML, not RSS**.
- **Verdict: REJECTED.** 4,681 raw CVE rows in a single fetch, carrying no severity and no
  exploitation status in the item, is precisely the "volume without exploitation signal"
  shape the brief said to skip for NVD. Confirmed exploitation is already covered by
  `cisa_kev`, and analyst-written advisories by `cisa_advisories`. Adoptable later **only**
  with a severity/exploited filter, which this endpoint does not expose per item.
- **Method note:** a naive `grep -c '<item>'` reported **0** items for this feed, because
  MSRC writes `<item Revision="1.0000000000">`. The real count came from an XML parser.
  A count that reads zero and a feed that is genuinely empty look identical.

## huggingface_blog — ADOPTED (was held in reserve in Phase 0.5)

- **Re-verified 2026-08-29** with one fresh call, as instructed.
- **Called:** `https://huggingface.co/blog/feed.xml`
- **Result:** HTTP 200, `application/rss+xml`, 251,388 bytes, 0.24 s, **852 `<item>`**.
- **Key:** none. `https://huggingface.co/robots.txt` is `User-agent: * / Allow: /`.
- **Fixture:** `tests/fixtures/huggingface_blog.xml` — trimmed from 852 to 3, chosen to
  include **one `isPermaLink="false"` community post** so both post families are exercised.
- **Verdict: ADOPTED.** `KIND = "stream"`; the adapter reads the head 30 items, the same
  choice `openai_news` makes, because the feed is a full archive rather than a window.
- **KNOWN LIMITATION, measured rather than assumed: no item carries a `<description>`** —
  **0 of 852**. Every observation's summary is therefore empty and the brief has only the
  title from this source. The adapter does **not** substitute the title or any other field
  into the summary; `test_huggingface_summary_is_empty_because_the_feed_has_no_description`
  pins that, so an adapter that starts inventing a summary fails loudly. (The *channel*
  carries a description; no *item* does — the first version of that test checked the
  document and had to be tightened to check items.)
- **Two post families, kept and labelled, not filtered:** official posts (`/blog/<slug>`,
  739) and community/organisation posts (`/blog/<org>/<slug>`, **113 of 852**). Org posts
  come from the model labs (IBM Granite, LiquidAI) and are often the substantive ones, so
  they are distinguished structurally in `extra["post_type"]` rather than dropped.
- **Identity:** `<guid>` equals `<link>` in every observed item, including the
  `isPermaLink="false"` ones, so the guid is a stable id and not a second URL form.

## frankfurter — ADOPTED (was verified-not-adopted in Phase 0.5)

- **Re-verified 2026-08-29.**
- **Called:** `https://api.frankfurter.dev/v1/latest?base=USD&symbols=EUR,JPY,GBP,CNY,CHF`
- **Result:** HTTP 200, `application/json`, 125 bytes, 0.61 s —
  `{"amount":1.0,"base":"USD","date":"2026-08-28","rates":{"CHF":0.80426,"CNY":6.7209,"EUR":0.85889,"GBP":0.73624,"JPY":159.68}}`
- **Key:** none. `https://api.frankfurter.dev/robots.txt` is `User-agent: * / Allow: /`.
- **Fixture:** `tests/fixtures/frankfurter.json` — the full real response, untrimmed.
- **Verdict: ADOPTED.** `KIND = "snapshot"` — the whole pair list arrives each fetch, so a
  pair disappearing is meaningful.
- **Identity (plan §5.11) is the PAIR, never the rate.** `upstream_id` is `"USD/EUR"`; the
  rate appears only in `extra["price"]` and the title carries no number. Guarded by
  `test_frankfurter_rate_is_never_part_of_identity`, which refetches the same pairs at
  moved rates and asserts identity is unchanged.
- **Honest labelling, the same care PAXG got.** These are **ECB reference rates published
  once per business day (~16:00 CET), not live tradable quotes.** `source_ts_ms` is the
  payload's own `date` field, so a weekend or holiday fetch reports Friday's reference date
  instead of looking fresh; `extra["rate_kind"] = "ecb_reference_daily"` says so on every
  row. Guarded by `test_frankfurter_reports_the_ecb_reference_date_not_fetch_time`.
- **Note on url:** Frankfurter has no per-pair web page, so the canonical url is that pair's
  own query (`…/v1/latest?base=USD&symbols=EUR`) — deterministic and resolvable, the same
  approach `openfda` uses.
- **Scope note:** FX is a beat dimension Phase 0.5 declined as unasked-for. It was adopted
  here on the lead's explicit instruction. **It does not close the markets gap** — equity
  indices and oil are still uncovered; see "Known coverage gap — markets" above, which
  stands unchanged.

## un_press — ADOPTED

**This is `press.un.org`, a DIFFERENT HOST from the `news.un.org` that Phase 0.5 rejected.**
That rejection turned on `Disallow: */news/` in news.un.org's rules; it is not inherited
here, and this verdict does not overturn it. press.un.org's own robots.txt was fetched and
read rather than assumed from the sibling.

- **Called:** `https://press.un.org/en/rss.xml`
- **Result:** HTTP 200, `application/rss+xml`, 7,176 bytes, **10 `<item>`**. Refetched 3
  times: 200 and 7,176 bytes every time.
- **Key:** none.
- **robots.txt** (`https://press.un.org/robots.txt`, 85 lines): a single `User-agent: *`
  group at line 16. Its Disallow entries cover only `/core/`, `/profiles/`, READMEs,
  `/admin/`, `/comment/reply/`, `/filter/tips`, `/node/add/`, `/search/`, `/search?`,
  `/user/*`, `/media/oembed`, their `/index.php/…` twins, `*/sitesearch` and `*/search`.
  **There is no `*/news/` rule and no rule matching `/en/rss.xml`.** No named-agent group
  exists, so there is no narrowly-scoped Allow of the kind that made news.un.org's case
  hard to argue.
- **Fixture:** `tests/fixtures/un_press.xml` — trimmed from 10 items to 4, deliberately
  **keeping the duplicate pair** described below so the dedup path is actually exercised.
- **Verdict: ADOPTED.** `KIND = "stream"`. This is the politics beat's first live
  general-news source; `state_dept_advisories` is a snapshot of country advisories and
  GDELT is still dark.
- **Identity is the UN DOCUMENT SYMBOL, not the url — because the feed publishes one
  meeting under two urls.** Found by reading the live payload: Security Council meeting
  **sc16444** appeared as both the press release
  (`/en/2026/sc16444.doc.htm`, "Kenscoff Massacre Exposes Worsening Brutality of Haiti's
  Gang Crisis…") and the live blog (`/en/blog/sc16444`, "Security Council, 10216th Meeting
  (PM) Haiti"). Keying on the url would have put the same Council meeting in the brief
  twice. Keying on the symbol collapses them, preferring the authoritative `.doc.htm`
  press release. Live run: **10 received, 9 accepted** — the collapse is visible in the
  counts. Guarded by `test_un_press_collapses_one_meeting_published_under_two_urls`.
- **Document-symbol prefixes** are mapped to a UN body in `extra["body"]` — observed live:
  `sgsm` 4 (SG statement), `sc` 3 (Security Council), `db` 1 (daily briefing), `bio` 1,
  `sga` 1. An unrecognised prefix is typed `"other"` with the raw prefix preserved in
  `extra["raw_prefix"]`, never silently relabelled — the same discipline
  `federal_register` applies to document types.
- Live run: **0 of 9 observations missing a timestamp**; all 9 document symbols unique.

## eu_council (Council of the EU press releases) — REJECTED (bot wall)

- **Called:** `https://www.consilium.europa.eu/en/rss/press-releases.aspx` and
  `https://www.consilium.europa.eu/en/press/press-releases/rss/`
- **Result:** **HTTP 403** on both, serving a `Browser check - Consilium` HTML interstitial
  with a meta-refresh — a managed anti-bot challenge, not a missing path.
- **Verdict: REJECTED.** Defeating a deliberate browser check is out of scope for a keyless
  monitor. `ec.europa.eu/commission/presscorner/api/rss?language=en` (European **Commission**,
  a different institution) did return HTTP 200 RSS and is the ready EU candidate if the beat
  ever needs one — recorded, not adopted, since `un_press` satisfied the brief's priority order.

## gdelt — RECHECKED 2026-08-29, STILL BROKEN, adapter unchanged

Ran the exact recheck command recorded above, at **2026-08-29T02:40:35Z**:

```
curl -sS -o /dev/null -w '%{http_code}\n' --max-time 15 \
  'https://api.gdeltproject.org/api/v2/doc/doc?query=test&mode=artlist&format=json&maxrecords=1'
→ curl: (60) SSL certificate problem: certificate has expired
→ 000
```

The certificate is byte-for-byte the same one, not a new short-lived cert:

```
subject= /CN=*.gdeltproject.org
issuer=  /C=US/O=Let's Encrypt/CN=YR2
notBefore=May 30 19:50:13 2026 GMT
notAfter= Aug 28 19:50:12 2026 GMT
```

**No change made to the adapter**, per instruction — it continues to return
`status="error"` cleanly and affects nothing else. **This has now been broken for ~31
hours and is past the "day or two" the Phase 0.5 note allowed, so it is a live decision
for the lead:** accept plaintext HTTP (rejected once, on the grounds that a brief quotes
these articles and plaintext can be edited in transit), drop GDELT, or keep waiting.
Politics is no longer one-source-deep while waiting — `un_press` now serves it alongside
`state_dept_advisories`.

## Live end-to-end run — all 13 against the real network

`uv run python` over `engine.monitor.adapters.ADAPTERS`, **2026-08-29T02:48:11Z**, real
network, no fixtures:

```
arxiv                  ai             healthy  http=200  recv=   25 acc=   25
openai_news            ai             healthy  http=200  recv= 1157 acc=   30
cisa_kev               cybersecurity  healthy  http=200  recv= 1685 acc= 1685
gdelt                  politics       error    http=None recv=    0 acc=    0
state_dept_advisories  politics       healthy  http=200  recv=  220 acc=  220
federal_register       healthcare     healthy  http=200  recv=   40 acc=   40
openfda                healthcare     healthy  http=200  recv=   25 acc=   25
coingecko              markets        healthy  http=200  recv=    3 acc=    3
treasury_yields        markets        healthy  http=200  recv=    4 acc=    4
huggingface_blog       ai             healthy  http=200  recv=  852 acc=   30
cisa_advisories        cybersecurity  healthy  http=200  recv=   30 acc=   30
un_press               politics       healthy  http=200  recv=   10 acc=    9
frankfurter            markets        healthy  http=200  recv=    5 acc=    5

healthy 12/13
```

**All four new sources are healthy against live endpoints.** The only failure is GDELT's
expired certificate, unchanged from Phase 0.5. `un_press`'s `recv=10 acc=9` is the
duplicate-meeting collapse firing on the real feed, not a dropped item.

---

# Phase 1b — `fred`, 2026-08-29 (the markets gap, closed)

Same discipline. This section closes the **"Known coverage gap — markets"** recorded in
Phase 0.5: no equity index, no oil. That gap's own note named FRED as the one keyed
source that could cover indices, oil and gold together. Kyle registered a free FRED key
on 2026-08-29; **it lives only in `deploy/compose/.env` on VM 107** and appears in no
file, fixture, log or commit here.

**Adopted: 1 source / 4 instruments (registry 13 → 14). Rejected: gold (no such series).**

Registry count is asserted, not assumed —
`uv run python -c "from engine.monitor.adapters import ADAPTERS; print(len(ADAPTERS))"`
returned **13 before** and **14 after**.

## fred

- **Called:** `https://api.stlouisfed.org/fred/series/observations?series_id=<ID>&api_key=<KEY>&file_type=json&sort_order=desc&limit=10`
  — one request per series. The `api_key` value is never written down; the key was read
  at call time with
  `ssh -i ~/.ssh/id_ed25519_pythia pythia@192.168.0.28 'grep "^FRED_API_KEY=" ~/pythia/deploy/compose/.env | cut -d= -f2-'`.
- **Key:** required. `FRED_API_KEY`, read from the environment at fetch time. A 32-hex
  string. Unset → the adapter returns `status="error"` with
  `"FRED_API_KEY not configured — no key, no call made"` and issues **no request**
  (verified live: `env -u FRED_API_KEY`, 2026-08-29).
- **Wrong key:** HTTP **400** with
  `{"error_code":400,"error_message":"Bad Request. The value for variable api_key is not registered..."}`.
  `_util.get` reports only `"HTTP 400"`, so the response body never reaches a log.

### Series verified — one real call each, 2026-08-29

| Series | HTTP | Bytes | Latest observation | Verdict |
|---|---|---|---|---|
| `SP500` (S&P 500) | 200 | 762 | 2026-08-28 = 7711.76 | **ADOPTED** |
| `DJIA` (Dow Jones Industrial Average) | 200 | 767 | 2026-08-28 = 53559.99 | **ADOPTED** |
| `NASDAQCOM` (NASDAQ Composite) | 200 | 767 | 2026-08-28 = 26402.42 | **ADOPTED** |
| `DCOILWTICO` (WTI spot, Cushing OK) | 200 | 753 | 2026-08-25 = 83.9 $/bbl | **ADOPTED** |
| `GOLDAMGBD228NLBM` (LBMA gold AM fix) | 400 | — | — | **REJECTED — series does not exist** |
| `GOLDPMGBD228NLBM` (LBMA gold PM fix) | 400 | — | — | **REJECTED — series does not exist** |

`curl` timings on those four: 0.29 s, 3.14 s, 1.03 s, 3.47 s.

### Gold — REJECTED, with evidence

Both LBMA gold fixings return
`{"error_code":400,"error_message":"Bad Request.  The series does not exist."}` from
`/fred/series?series_id=…`. They are gone, not stale.

A search for a replacement found none:
`/fred/series/search?search_text=gold+price&order_by=popularity&limit=15` returns
**no spot gold price series** — the top results are `GVZCLS` (CBOE *gold ETF volatility*
index), `NASDAQQGLDI` (a Credit Suisse gold *flows* index), and a run of PPI / import-export
*price indices* for gold ore and jewellery. `search_text=London+Bullion+Market` returns
**`count: 0`**.

**Gold is therefore NOT added.** It stays on `coingecko`'s PAXG proxy, which is already
labelled a proxy. Shipping a discontinued LBMA fixing would have put a stale number in the
brief wearing a current date.

### Data lag — recorded because it is not uniform

These are **daily close** values, and the two families lag by different amounts. Observed
2026-08-29: the three equity series were at **2026-08-28**, `DCOILWTICO` (EIA-sourced) at
**2026-08-25** — three days behind, with its own `realtime_start` at 2026-08-26. The
adapter stamps `source_ts_ms` from each observation's **own date**, so the brief cannot
render Monday's oil price as today's. `extra["value_kind"] = "daily_close"` says the same
thing in the record.

### Missing values are real and had to be handled

FRED publishes a row for every calendar weekday and writes `"."` where the series has no
value. Confirmed live on SP500 over 2025-12-20…2026-01-05:

```
2025-12-24 6932.05
2025-12-25 .          <- Christmas
2025-12-26 6929.94
...
2026-01-01 .          <- New Year's Day
2026-01-02 6858.47
```

So the newest **row** is not always the newest **value**. `latest_value()` walks the
descending window (`limit=10`, enough for any run of market holidays) and takes the first
row that parses as a number. A window that is entirely `"."` yields no observation for that
series — counted in `received`, not in `accepted`, never rendered as a zero.

### Fixture

`tests/fixtures/fred.json` — the four real payloads, keyed by series id, exactly as
recorded (10 observations each). **One deliberate addition, called out here because it is
the only fixture in this repo that is not purely a trimmed capture:** a single row
`{"date": "2026-08-29", "value": "."}` was prepended to `SP500.observations` so the
holiday path above is exercised by the test suite. The row's shape is copied verbatim
from the live 2025-12-25 row; no field was invented and no real value was altered.

The fixture holds no request URL and no key — asserted by
`test_fred_fixture_holds_no_api_key`, which greps every fixture for `api_key` and greps
fred's for a bare 32-hex run. A repo-wide sweep for the real key value
(`grep -rIlF "$KEY"` over the working tree, and `git grep -IlF`) returned **0 hits**, and
the sweep was proved to fire first against a planted canary file containing the key
(**1 hit**).

### Canonical URL

Each observation links to that series' own FRED page, e.g.
`https://fred.stlouisfed.org/series/SP500` — derived from the id, never invented per
fetch, and keyless. All four verified 2026-08-29: HTTP 200, titles
`S&P 500 (SP500) | FRED | St. Louis Fed`, `Dow Jones Industrial Average (DJIA) …`,
`NASDAQ Composite (NASDAQCOM) …`, `Crude Oil Prices: West Texas Intermediate (WTI) -
Cushing, Oklahoma (DCOILWTICO) …`. (An earlier attempt at these four timed out; the same
minute GDELT and FRED's own terms page also timed out, so that was local network
flakiness, not a bot wall — the retry succeeded in 0.5 s.)

### Terms of use — VERDICT: permitted, with one live constraint

Read in full at <https://fred.stlouisfed.org/docs/api/terms_of_use.html> (2026-08-29).

**Permitted.** Nothing in the Prohibitions applies: this is not a replica of the FRED web
experience, it does not conceal its identity (`User-Agent: PythiaMonitor/0.5 …`), four
requests every half hour is not unreasonable bandwidth, and no FRED mark is used in a
hostname.

**Required, and now carried in code.** The terms say: *"Place the following notice
prominently on your application: 'This product uses the FRED® API but is not endorsed or
certified by the Federal Reserve Bank of St. Louis.'"* That exact sentence is
`fred.TERMS_NOTE` (persisted to the `sources` table via `terms_note`) and is repeated on
every observation as `extra["fred_notice"]`, so a brief can render it.

**The constraint the lead should see.** The terms also say third-party series carry their
owners' restrictions, and that *"Before using data series owned by third parties for
anything other than your own personal use, you must contact the data owner to obtain
permission"*; copyrighted series are identified by the word *Copyright* in their notes.
Checked per series via `/fred/series?series_id=…`:

| Series | Owner note | `extra["redistribution"]` |
|---|---|---|
| `SP500` | *"Copyright © 2016, S&P Dow Jones Indices LLC… Reproduction of S&P 500 in any form is prohibited except with the prior written permission of S&P Dow Jones Indices LLC"* | `restricted` |
| `DJIA` | same S&P Dow Jones notice | `restricted` |
| `NASDAQCOM` | *"Copyright © 2016, NASDAQ OMX Group, Inc."* | `restricted` |
| `DCOILWTICO` | no copyright word; EIA (US government) source note only | `public_domain` |

PYTHIA Monitor is a **private** brief for one person, which is the "own personal use" the
terms carve out, so adoption is inside the licence as things stand. But the moment a brief
carrying an index level is published, shared or exposed to a third party, those three
series need S&P DJI / NASDAQ permission. That is a fact about the product, not about this
adapter, so it is recorded as a **field on every observation** rather than only as prose —
`extra["redistribution"]` — and guarded by
`test_fred_records_the_redistribution_terms_it_is_bound_by`. **Decision for the lead: if
the brief is ever to leave personal use, either obtain permission or drop SP500/DJIA/
NASDAQCOM and keep DCOILWTICO.**

### Markets coverage after this

The Phase 0.5 gap table now reads:

| Instrument | Status |
|---|---|
| BTC, ETH | covered — `coingecko` |
| Gold | **proxy only** — PAXG; FRED has no spot gold series (evidence above) |
| Treasury yields (3M, 2Y, 10Y, 30Y) | covered — `treasury_yields` |
| FX (USD vs EUR/JPY/GBP/CHF/CNY) | covered — `frankfurter` |
| Major equity indices (S&P 500, Dow, Nasdaq) | **covered — `fred`** |
| Oil (WTI) | **covered — `fred`** |

### Live end-to-end run — all 14 against the real network

`uv run python` over `engine.monitor.adapters.ADAPTERS`, **2026-08-29T12:06:13Z**, real
network, real key, no fixtures:

```
arxiv                  ai             healthy  http=200  recv= 25   acc= 25
openai_news            ai             healthy  http=200  recv= 1157 acc= 30
huggingface_blog       ai             healthy  http=200  recv= 852  acc= 30
cisa_kev               cybersecurity  healthy  http=200  recv= 1685 acc= 1685
cisa_advisories        cybersecurity  healthy  http=200  recv= 30   acc= 30
gdelt                  politics       error    http=None recv= 0    acc= 0   ConnectTimeout
state_dept_advisories  politics       healthy  http=200  recv= 220  acc= 220
un_press               politics       healthy  http=200  recv= 10   acc= 9
federal_register       healthcare     healthy  http=200  recv= 40   acc= 40
openfda                healthcare     healthy  http=200  recv= 25   acc= 25
coingecko              markets        healthy  http=200  recv= 3    acc= 3
treasury_yields        markets        healthy  http=200  recv= 4    acc= 4
frankfurter            markets        healthy  http=200  recv= 5    acc= 5
fred                   markets        healthy  http=200  recv= 4    acc= 4

healthy 13/14
```

`fred` observations from that run:

```
SP500       price=7711.76   date=2026-08-28  redist=restricted
DJIA        price=53559.99  date=2026-08-28  redist=restricted
NASDAQCOM   price=26402.42  date=2026-08-28  redist=restricted
DCOILWTICO  price=83.9      date=2026-08-25  redist=public_domain
```

The key appeared in no title, url, extra or error in that run (asserted in the same script).

**GDELT note, not acted on:** it failed this run as `ConnectTimeout`, a *different* symptom
from the expired certificate recorded above. The same minute, two other hosts also timed
out from this machine, so this run is not evidence the certificate was replaced — GDELT's
status is unchanged and still the lead's open decision.
