# Feed verification — Phase 0.5 (Lane F)

Every source below was called for real from this machine before any adapter was
written. A source named in `PYTHIA-MONITOR-V1-PLAN.md` §8 is a **candidate**; what
makes it a fact is a recorded response, and that response is the fixture the parser
is written against.

**All calls made 2026-08-28** (machine local time; UTC stamps where they matter).
Fixtures live in `tests/fixtures/`, trimmed where noted — trimming removes items,
never fields, so every parsed field is a real one.

**Adopted: 9.  Rejected: 5.  Verified but held in reserve: 2.**

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
| Major equity indices (S&P 500, Dow, Nasdaq) | **NOT COVERED** |
| Oil | **NOT COVERED** |

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
