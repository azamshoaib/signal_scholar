# SignalScholar — Project Plan

A research discovery tool that cuts through Google Scholar noise for STEM grad students and early-career researchers, by surfacing high-signal papers based on author/lab reputation and smarter impact metrics — not just raw citation counts.

## Target User
Grad students and early-career researchers across STEM fields who find Google Scholar's results too noisy to efficiently identify strong papers and strong labs.

## Core Concept
Three entry points, one ranking engine underneath:

1. **Topic search** → query re-ranked by quality signals, not just relevance/recency
2. **Paper-in, papers-out** → "more like this, but better" using citation graphs + semantic similarity
3. **Follow labs/authors** → personalized feed of new output from people you trust

## Data Sources (combined)

| Source | Why | What it gives you |
|---|---|---|
| **OpenAlex** | Free, no rate-limit headaches, huge open catalog | Full metadata, citation graph, author/institution IDs |
| **Semantic Scholar API** | Best-in-class semantic embeddings + "highly influential citations" | Similarity search, TLDR summaries, influence-weighted citations |
| **CrossRef** | Ground-truth publication metadata | DOI resolution, venue data |
| **arXiv API** (later) | Preprints, STEM-heavy | Freshness for fast-moving fields (ML, physics) |

**Recommendation:** OpenAlex as the primary backbone (free, broad coverage), Semantic Scholar for the embeddings/influence layer, arXiv as a freshness supplement later.

## The Ranking Engine

This is the key differentiator from Scholar. It blends author/lab reputation with impact signals beyond raw citation count.

### Author/Lab Reputation Score
- h-index *normalized by academic age* — so strong early-career researchers aren't buried under senior PIs
- Institution/lab track record **in that specific subfield** (a good lab in immunology ≠ automatically good in ML)
- Author's recent trajectory (rising vs. coasting on old work)

### Impact Signals (beyond raw citation count)
- **Citation velocity** — citations per year since publication, not lifetime total (surfaces good recent papers that haven't had time to accumulate citations)
- **Highly-influential-citation ratio** (exposed by Semantic Scholar) — filters out papers only cited in passing/related-work dumps
- **Cross-field citation diversity** — cited across multiple subfields = broader impact signal
- **Venue reputation** — weighted lightly, since great work sometimes lands in mid-tier venues

### Scoring Approach
Combine these into one score with **adjustable weights** — a slider UI ("prioritize reputation" vs. "prioritize recency/velocity") lets users move away from one fixed formula. Start with a transparent weighted formula before considering ML-based re-ranking.

## MVP Feature Set
1. Topic search box → ranked results (not just Scholar's relevance sort)
2. Paper detail page with a score breakdown — transparency on *why* a paper ranked where it did
3. "Similar but better" button on any paper
4. Follow author/lab → simple feed of new work
5. Basic filters: year range, field, minimum citation velocity

## Suggested Tech Stack
- **Backend:** Python (FastAPI) — easiest for wrangling academic APIs and any ML/embedding work
- **Frontend:** Next.js / React — dashboard-style UI, mature ecosystem
- **Database:** Postgres — cache API results and computed scores, avoid hammering rate limits
- **Ranking:** start with a weighted formula (transparent, debuggable) before reaching for ML re-ranking

## Phased Roadmap
1. **Phase 1:** Single data source (OpenAlex), topic search, basic reputation + velocity scoring
2. **Phase 2:** Add Semantic Scholar embeddings for "similar paper" feature
3. **Phase 3:** Author/lab following + feed
4. **Phase 4:** Personalization (learn from what the user clicks/saves)

## Suggested Next Step (before writing code)
Pick 5–10 papers already known to be great in your field, and 5–10 that are mediocre-but-highly-cited. Manually inspect what signals actually separate them. This grounds the scoring formula's weights in real examples instead of guesswork.
