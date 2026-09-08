// GitHub issue #19: client-side re-sort of already-rendered search results
// when the user drags the reputation/velocity weight slider.
//
// The slider (`#weight-slider`) and its label (`#weight-label`) live
// inside `papers/_results.html`, which is destroyed and recreated by every
// HTMX swap of `#results` (a new search, a changed filter per #18). A
// listener bound directly to today's slider element would silently stop
// firing after the first search, so this attaches exactly one delegated
// `input` listener on `document` at load time -- it keeps working across
// swaps with no rebinding code, per #19's Constraints.
//
// This script is loaded once, outside the swapped `#results` div (see
// `papers/search.html`), so it never re-executes on a partial swap.
document.addEventListener("input", function (event) {
  if (event.target.id !== "weight-slider") {
    return;
  }

  var reputationPct = parseInt(event.target.value, 10);
  var velocityPct = 100 - reputationPct;

  var label = document.getElementById("weight-label");
  if (label) {
    label.textContent = reputationPct + "% reputation / " + velocityPct + "% velocity";
  }

  var list = document.getElementById("results-list");
  if (!list) {
    return;
  }

  var rows = Array.prototype.slice.call(list.children);
  var scored = rows.map(function (row) {
    var reputationScore = parseFloat(row.getAttribute("data-reputation-score"));
    var velocityScore = parseFloat(row.getAttribute("data-velocity-score"));
    var score = (reputationPct / 100) * reputationScore + (velocityPct / 100) * velocityScore;

    var scoreEl = row.querySelector(".score-value");
    if (scoreEl) {
      scoreEl.textContent = "Score: " + score.toFixed(1);
    }

    return {
      row: row,
      score: score,
      paperId: parseInt(row.getAttribute("data-paper-id"), 10),
    };
  });

  // Descending by score, tiebreaking ascending by paper id -- matching
  // #15's server-side `-combined_score, id` ordering convention, so the
  // order at the slider's default position visually matches the order the
  // page loaded with.
  scored.sort(function (a, b) {
    if (b.score !== a.score) {
      return b.score - a.score;
    }
    return a.paperId - b.paperId;
  });

  // `appendChild` on a node already in the DOM moves it rather than
  // duplicating it -- this reorders the existing `<li>` nodes in place.
  scored.forEach(function (entry) {
    list.appendChild(entry.row);
  });
});
