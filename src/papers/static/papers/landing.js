// Landing page motion only — scroll-reveal for cards/steps, and a subtle
// pointer-follow tilt on the blob field. No framework, no dependency;
// mirrors the vanilla-JS approach already used by weight_slider.js.
(function () {
  "use strict";

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var revealTargets = document.querySelectorAll(".card, .step");
  if (revealTargets.length && "IntersectionObserver" in window) {
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.15 }
    );
    revealTargets.forEach(function (el) {
      observer.observe(el);
    });
  } else {
    revealTargets.forEach(function (el) {
      el.classList.add("is-visible");
    });
  }

  if (!reduceMotion) {
    var field = document.querySelector(".blob-field");
    if (field) {
      var raf = null;
      document.addEventListener("pointermove", function (event) {
        if (raf) return;
        raf = requestAnimationFrame(function () {
          var xPct = (event.clientX / window.innerWidth - 0.5) * 2;
          var yPct = (event.clientY / window.innerHeight - 0.5) * 2;
          field.style.transform =
            "translate(" + xPct * 12 + "px, " + yPct * 12 + "px)";
          raf = null;
        });
      });
    }
  }
})();
