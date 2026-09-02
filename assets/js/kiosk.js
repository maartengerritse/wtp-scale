/* ==========================================================================
   WTP Scale kiosk controller — September 2026

   The page loads once and never navigates. It polls /state for the tag
   currently on the reader and moves between three views:

     welcome  ->  loading (checklist)  ->  product  ->  welcome

   Dev mode (no Pi, no reader): open with ?dev
     - press 1..9 / 0 to simulate placing that product on the scale
     - press Escape to simulate lifting it
   ========================================================================== */

(function () {
  "use strict";

  var POLL_MS = 250;
  var DEV = new URLSearchParams(location.search).has("dev");

  var data = null;
  var byTag = Object.create(null);
  var view = "welcome";
  var currentProduct = null;
  var loadingTimers = [];
  var clearTimer = null;
  var lastSeenTag = null;

  var el = {
    views: {
      welcome: document.getElementById("view-welcome"),
      loading: document.getElementById("view-loading"),
      product: document.getElementById("view-product")
    },
    welcomeVideo: document.getElementById("welcome-video"),
    loadingVideo: document.getElementById("loading-video"),
    productVideo: document.getElementById("product-video"),
    receipt: document.getElementById("receipt"),
    steps: document.getElementById("loading-steps"),
    name: document.getElementById("product-name"),
    materials: document.getElementById("materials"),
    distribution: document.getElementById("distribution"),
    totals: document.getElementById("totals"),
    origin: document.getElementById("origin"),
    originFlag: document.getElementById("origin-flag"),
    originCountry: document.getElementById("origin-country"),
    specs: document.getElementById("specs"),
    impact: document.getElementById("impact"),
    footer: document.getElementById("footer"),
    fatal: document.getElementById("fatal")
  };

  /* ---------------------------------------------------------- utilities -- */

  function fatal(message) {
    el.fatal.textContent = message;
    el.fatal.hidden = false;
  }

  function row(label, value, classes) {
    var wrap = document.createElement("div");
    if (classes) wrap.className = classes;
    var dt = document.createElement("dt");
    dt.textContent = label;
    var dd = document.createElement("dd");
    dd.textContent = value;
    wrap.appendChild(dt);
    wrap.appendChild(dd);
    return wrap;
  }

  function setField(id, value) {
    var node = document.getElementById(id);
    node.textContent = value || "";
    if (node.parentElement.classList.contains("specs__label") === false) {
      node.parentElement.classList.toggle("is-empty", !value);
    }
  }

  /* Play a video defensively.
     autoplay can be refused, and a video that is already buffered may never
     fire another event. Always try play() and ignore the rejection. */
  function play(video) {
    if (!video) return;
    var attempt = video.play();
    if (attempt && typeof attempt.catch === "function") attempt.catch(function () {});
  }

  /* ------------------------------------------------------------- render -- */

  function renderReceipt(p) {
    el.materials.textContent = "";
    (p.materials || []).forEach(function (m) {
      el.materials.appendChild(row(m.label, m.value));
    });
    if (p.materialTotal) {
      el.materials.appendChild(row("Total Material Costs", p.materialTotal, "row--strong row--rule"));
    }

    el.distribution.textContent = "";
    (p.distribution || []).forEach(function (d) {
      var classes = d.bold ? "row--strong" : "";
      if (d.label === "Cost of Sales") classes += " row--rule";
      el.distribution.appendChild(row(d.label, d.value, classes.trim()));
    });

    el.totals.textContent = "";
    if (p.totals) {
      if (p.totals.exWorks) {
        el.totals.appendChild(row("Total (ex works)", p.totals.exWorks, "row--strong row--rule"));
      }
      if (p.totals.totalCosts) {
        el.totals.appendChild(row("Total Costs", p.totals.totalCosts, "row--grand"));
      }
    }
  }

  /* Shrink the receipt until it fits its column.

     Shower Gel has 13 material lines; on a 1366x768 venue screen that pushed
     "Total Costs" below the fold, which is the one number the whole demo
     exists to show. Rather than clip, scale the card down until it fits. */
  function fitReceipt() {
    var card = el.receipt;
    var max = parseFloat(getComputedStyle(document.documentElement)
      .getPropertyValue("--u")) || 16;
    var size = max;
    card.style.fontSize = size + "px";

    // Bounded loop: never fewer than 55% of full size, never more than 24 steps.
    var floor = max * 0.55;
    var guard = 24;
    while (card.scrollHeight > card.clientHeight && size > floor && guard-- > 0) {
      size -= max * 0.02;
      card.style.fontSize = size + "px";
    }
  }

  function renderDetail(p) {
    el.name.textContent = "";
    el.name.appendChild(document.createTextNode(p.name));
    if (p.subtitle) {
      var sub = document.createElement("span");
      sub.textContent = " | " + p.subtitle;
      el.name.appendChild(sub);
    }

    var specs = p.specs || {};
    var origin = specs.origin;
    if (origin && origin.country) {
      el.originCountry.textContent = origin.country;
      el.originFlag.src = "assets/img/flags/" + (origin.code || "").toLowerCase() + ".svg";
      el.originFlag.alt = origin.country;
      el.origin.hidden = false;
    } else {
      el.origin.hidden = true;
    }

    setField("spec-dimensions", specs.dimensions);
    setField("spec-weight", specs.weight);
    setField("spec-ean", specs.ean);
    setField("spec-naics", specs.naics);
    // Hide the whole block when there is nothing at all to show.
    var anySpec = specs.dimensions || specs.weight || specs.ean || specs.naics;
    el.specs.hidden = !anySpec;

    var s = p.sustainability;
    var hasImpact = s && (s.social || s.environmental || s.total || s.co2eq);
    if (hasImpact) {
      document.getElementById("impact-social").textContent = s.social || "—";
      document.getElementById("impact-environmental").textContent = s.environmental || "—";
      document.getElementById("impact-total").textContent = s.total || "—";
      document.getElementById("impact-co2").textContent = s.co2eq || "—";
    }
    el.impact.hidden = !hasImpact;

    // Swap src rather than keeping one <video> per product: the Pi should
    // only ever decode one product clip at a time.
    var src = "assets/video/" + p.video;
    if (el.productVideo.getAttribute("src") !== src) {
      el.productVideo.setAttribute("src", src);
      el.productVideo.load();
    }
    play(el.productVideo);
  }

  /* -------------------------------------------------------------- views -- */

  function show(next) {
    if (view === next) return;
    Object.keys(el.views).forEach(function (key) {
      el.views[key].classList.toggle("is-active", key === next);
    });
    view = next;

    if (next === "welcome") play(el.welcomeVideo);
    if (next === "loading") play(el.loadingVideo);
    if (next === "product") play(el.productVideo);
  }

  function clearLoadingTimers() {
    loadingTimers.forEach(clearTimeout);
    loadingTimers = [];
  }

  function startLoading(product) {
    clearLoadingTimers();
    currentProduct = product;

    var steps = Array.prototype.slice.call(el.steps.children);
    steps.forEach(function (li) { li.classList.remove("is-done"); });

    show("loading");

    var total = (data.config && data.config.loadingSeconds) || 10;
    var per = (total * 1000) / Math.max(steps.length, 1);

    steps.forEach(function (li, i) {
      loadingTimers.push(setTimeout(function () {
        li.classList.add("is-done");
      }, per * (i + 1)));
    });

    loadingTimers.push(setTimeout(function () {
      renderReceipt(product);
      renderDetail(product);
      show("product");
      fitReceipt();
    }, total * 1000));
  }

  function goWelcome() {
    clearLoadingTimers();
    currentProduct = null;
    show("welcome");
  }

  /* ---------------------------------------------------------- tag input -- */

  function onTag(tagId) {
    if (tagId) {
      if (clearTimer) { clearTimeout(clearTimer); clearTimer = null; }

      var product = byTag[String(tagId)];
      if (!product) return;                       // unknown tag: ignore, stay put
      if (currentProduct && currentProduct.id === product.id) return;
      startLoading(product);
      return;
    }

    // Tag lifted. Only start the countdown once the product is actually on
    // screen: if someone lifts the item mid-calculation we still finish the
    // loading animation and show them the result, rather than snapping back
    // to the welcome screen having shown nothing. (The old Selenium version
    // blocked for 14s and behaved this way by accident; here it is deliberate.)
    if (view === "product" && !clearTimer) {
      var delay = (data.config && data.config.returnDelaySeconds) || 1;
      clearTimer = setTimeout(function () {
        clearTimer = null;
        goWelcome();
      }, delay * 1000);
    }
  }

  function poll() {
    fetch("/state", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (s) {
        var tag = s && s.tag ? String(s.tag) : null;
        if (tag !== lastSeenTag) {
          lastSeenTag = tag;
        }
        onTag(tag);
      })
      .catch(function () { /* reader service not up yet; keep polling */ })
      .then(function () { setTimeout(poll, POLL_MS); });
  }

  /* ---------------------------------------------------------------- dev -- */

  function enableDevMode() {
    var order = data.products;
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { onTag(null); return; }
      var n = parseInt(e.key, 10);
      if (isNaN(n)) return;
      var index = n === 0 ? 9 : n - 1;
      var p = order[index];
      if (!p) return;
      if (clearTimer) { clearTimeout(clearTimer); clearTimer = null; }
      if (currentProduct && currentProduct.id === p.id) return;
      startLoading(p);
    });
    // Test hook: lets a layout sweep render every product without sitting
    // through the loading animation each time. Dev mode only.
    window.__kiosk = {
      products: data.products,
      showProduct: function (p) {
        clearLoadingTimers();
        currentProduct = p;
        renderReceipt(p);
        renderDetail(p);
        show("product");
        fitReceipt();
      }
    };

    console.log("dev mode: press 1-9/0 for a product, Escape to clear");
  }

  /* --------------------------------------------------------------- boot -- */

  function buildSteps() {
    el.steps.textContent = "";
    (data.loadingSteps || []).forEach(function (label) {
      var li = document.createElement("li");
      var icon = document.createElement("span");
      icon.className = "step__icon";
      var text = document.createElement("span");
      text.textContent = label;
      li.appendChild(icon);
      li.appendChild(text);
      el.steps.appendChild(li);
    });
  }

  fetch("products.json", { cache: "no-store" })
    .then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(function (doc) {
      data = doc;
      (data.products || []).forEach(function (p) {
        (p.tagIds || []).forEach(function (t) { byTag[String(t)] = p; });
      });

      buildSteps();
      el.footer.textContent = (data.config && data.config.footer) || "";

      show("welcome");
      play(el.welcomeVideo);

      window.addEventListener("resize", function () {
        if (view === "product") fitReceipt();
      });

      if (DEV) enableDevMode();
      else poll();
    })
    .catch(function (err) {
      fatal(
        "Could not load products.json (" + err.message + "). " +
        "The kiosk must be served over HTTP — open http://localhost:8080, not the file directly."
      );
    });
})();
