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
  var displayCurrency = null;   // what the page is currently rendering in

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
    readerWarn: document.getElementById("reader-warning"),
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
    // Dotted leader between label and figure, receipt style. A real element
    // rather than a ::after so long material names wrap cleanly around it.
    var leader = document.createElement("span");
    leader.className = "leader";
    var dd = document.createElement("dd");
    dd.textContent = value;
    wrap.appendChild(dt);
    wrap.appendChild(leader);
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

  /* ----------------------------------------------------------- currency --

     Amounts in products.json are numbers in the currency each product was
     exported in ("currency" on the product, else config.currency). The kiosk
     can display either, converting at config.usdPerEur -- a fixed rate, since
     the Pi is offline and cannot look one up. */

  var SYMBOLS = { EUR: "€", USD: "$" };

  function convert(amount, from, to) {
    if (from === to) return amount;
    var rate = (data && data.config && data.config.usdPerEur) || 1;
    return from === "EUR" ? amount * rate : amount / rate;
  }

  /* How many decimals an amount is quoted to: round to 4, drop trailing
     zeros, keep at least 2. This rule reproduces almost every amount the file
     used to carry as a display string. */
  function decimalsFor(value) {
    var frac = (value.toFixed(4).replace(/0+$/, "").split(".")[1] || "");
    return Math.max(2, frac.length);
  }

  function decimalise(value, decimals) {
    // Trim trailing zeros the conversion introduced -- USD 0,2691 becomes
    // EUR 0,23 rather than 0,2300 -- but never fewer than two decimals.
    var text = value.toFixed(decimals);
    if (text.indexOf(".") >= 0) {
      text = text.replace(/0+$/, "");
      var frac = text.split(".")[1] || "";
      while (frac.length < 2) { text += "0"; frac += "0"; }
    }
    return text.replace(".", ",");
  }

  function money(amount, sourceCurrency) {
    if (typeof amount !== "number" || isNaN(amount)) return "";
    var from = sourceCurrency || (data && data.config && data.config.currency) || "EUR";
    var to = displayCurrency || from;
    // Quote the converted figure to the same precision as the source, so a
    // €0,08 material does not become $0,0936 through the exchange rate.
    return (SYMBOLS[to] || "") +
           decimalise(convert(amount, from, to), decimalsFor(amount));
  }

  function weight(value) {
    return typeof value === "number" ? decimalise(value, decimalsFor(value)) : "";
  }


  /* Play a video defensively.
     autoplay can be refused, and a video that is already buffered may never
     fire another event. Always try play() and ignore the rejection. */
  function play(video) {
    if (!video) return;
    var attempt = video.play();
    if (attempt && typeof attempt.catch === "function") attempt.catch(function () {});
  }

  /* Tell the reader service what the page is doing. It prints these to the
     journal, so `journalctl --user -u wtp-kiosk -f` shows tag reads and view
     changes side by side. Fire-and-forget; in dev mode there is no server. */
  function report(event, extra) {
    try {
      fetch("/log", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event: event, data: extra || {} })
      }).catch(function () {});
    } catch (e) { /* ignore */ }
  }

  /* Video watchdog.

     On the Pi the hardware decoder starves a few seconds before the end of a
     clip: measured on intro.mp4, currentTime froze at 74.9s of 78.0s with
     paused=false, ended=false, readyState=2. `ended` never fires, so neither
     the loop attribute nor an ended handler can restart it. So watch the
     playhead: if the visible clip is meant to be playing and has not moved,
     or is inside its last moments, wrap it ourselves. A restart that does
     not take escalates to a full reload of the element. */
  var watch = { lastT: {}, stuckSince: {}, restartedAt: {}, loadingSince: {} };

  function activeVideo() {
    if (view === "welcome") return el.welcomeVideo;
    if (view === "loading") return el.loadingVideo;
    return el.productVideo;
  }

  function watchVideos() {
    var active = activeVideo();
    var now = Date.now();
    var cfg = (data && data.config) || {};
    // The early wrap exists for the 78s welcome clip, whose last ~3s the Pi
    // cannot decode. Applied to a 13s loading clip it would cut a quarter of
    // it; the shorter clips only need the stall detector as a safety net.
    var welcomeWrap = typeof cfg.wrapBeforeEndSeconds === "number" ? cfg.wrapBeforeEndSeconds : 0.5;

    [el.welcomeVideo, el.loadingVideo, el.productVideo].forEach(function (v) {
      var id = v.id;
      if (v !== active || !v.currentSrc) {
        watch.stuckSince[id] = 0;
        watch.loadingSince[id] = 0;
        delete watch.lastT[id];
        return;
      }
      if (v.paused) play(v);

      var t = v.currentTime;

      // A clip that is still buffering has not stalled: readyState stays below
      // HAVE_FUTURE_DATA and the playhead legitimately sits at 0. Counting that
      // as a stall made this reload the element every second, so a large clip
      // never finished loading at all -- which is exactly what happened when
      // the product videos grew from ~2 MB to ~9 MB.
      if (v.readyState < 3) {
        if (!watch.loadingSince[id]) watch.loadingSince[id] = now;
        var loadingMs = now - watch.loadingSince[id];
        var retriedRecently = watch.restartedAt[id] && now - watch.restartedAt[id] < 15000;
        // Genuinely never arriving is still worth one retry, but slowly.
        if (loadingMs > 15000 && !retriedRecently) {
          report("video-reload", { id: id, reason: "never-loaded",
                                   readyState: v.readyState,
                                   error: v.error ? v.error.code : null });
          v.load();
          play(v);
          watch.restartedAt[id] = now;
        }
        watch.lastT[id] = t;
        return;
      }
      watch.loadingSince[id] = 0;

      var wrapBefore = v === el.welcomeVideo ? welcomeWrap : 0.25;
      var nearEnd = v.duration > 0 && t > v.duration - wrapBefore;
      var frozen = watch.lastT[id] !== undefined && Math.abs(t - watch.lastT[id]) < 0.001 && !v.paused;
      if (frozen) {
        if (!watch.stuckSince[id]) watch.stuckSince[id] = now;
      } else {
        watch.stuckSince[id] = 0;
      }
      var stuckMs = watch.stuckSince[id] ? now - watch.stuckSince[id] : 0;
      var recently = watch.restartedAt[id] && now - watch.restartedAt[id] < 2000;

      if ((nearEnd || stuckMs > 1000) && !recently) {
        var reason = nearEnd ? "near-end" : "stalled";
        var escalate = reason === "stalled" && watch.restartedAt[id] && now - watch.restartedAt[id] < 8000;
        report(escalate ? "video-reload" : "video-restart",
               { id: id, t: +t.toFixed(2), duration: +(v.duration || 0).toFixed(2), reason: reason });
        if (escalate) {
          v.load();
        } else {
          v.currentTime = 0;
        }
        play(v);
        watch.restartedAt[id] = now;
        watch.stuckSince[id] = 0;
      }
      watch.lastT[id] = v.currentTime;
    });
  }

  /* ------------------------------------------------------------- render -- */

  function renderReceipt(p) {
    var cur = p.currency;
    el.materials.textContent = "";
    (p.materials || []).forEach(function (m) {
      el.materials.appendChild(row(m.label, money(m.value, cur)));
    });
    if (typeof p.materialTotal === "number") {
      el.materials.appendChild(
        row("Total Material Costs", money(p.materialTotal, cur), "row--strong row--rule"));
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
      if (typeof p.totals.totalCosts === "number") {
        el.totals.appendChild(row("Total Costs", money(p.totals.totalCosts, cur), "row--grand"));
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
      document.getElementById("impact-social").textContent = money(s.social, p.currency) || "—";
      document.getElementById("impact-environmental").textContent = money(s.environmental, p.currency) || "—";
      document.getElementById("impact-total").textContent = money(s.total, p.currency) || "—";
      document.getElementById("impact-co2").textContent = weight(s.co2eq) || "—";
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
    report("view", { view: next, product: currentProduct ? currentProduct.id : null });

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
      if (!product) {                             // unknown tag: ignore, stay put
        if (tagId !== lastSeenTag) report("unknown-tag", { tag: String(tagId) });
        return;
      }
      if (currentProduct && currentProduct.id === product.id) return;
      report("tag", { tag: String(tagId), product: product.id });
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
        // Discreet on-screen warning when the reader hardware is not answering,
        // so a loose cable is obvious at the stand instead of looking like
        // "tags just don't work today".
        // The Pi app writes the chosen currency; apply it live rather than
        // making someone restart the kiosk to see the switch.
        var wanted = (s && s.currency) ||
                     (data && data.config && data.config.currency) || "EUR";
        if (wanted !== displayCurrency) {
          displayCurrency = wanted;
          report("currency", { currency: wanted });
          if (view === "product" && currentProduct) {
            renderReceipt(currentProduct);
            renderDetail(currentProduct);
            fitReceipt();
          }
        }

        var missing = s && s.reader === "missing";
        el.readerWarn.hidden = !missing;
        if (missing) el.readerWarn.textContent = "RFID reader not detected" + (s.readerInfo ? " \u2013 " + s.readerInfo : "");
        // Dev mode drives the views from the keyboard, so ignore the reader
        // here -- but still take the currency, so the switch is testable
        // without hardware.
        if (!DEV) onTag(tag);
        lastSeenTag = tag;
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

      displayCurrency = (data.config && data.config.currency) || "EUR";
      buildSteps();
      el.footer.textContent = (data.config && data.config.footer) || "";

      // The <video loop> attribute should be enough, but the Pi's hardware
      // decoder has been seen to stop at the end of a clip instead of looping.
      // Restarting on `ended` costs nothing and guarantees the ambient clips
      // never freeze on a last frame during a long day on the stand.
      [el.welcomeVideo, el.loadingVideo, el.productVideo].forEach(function (v) {
        v.addEventListener("ended", function () {
          v.currentTime = 0;
          play(v);
        });
      });

      show("welcome");
      play(el.welcomeVideo);

      setInterval(watchVideos, 500);

      window.addEventListener("resize", function () {
        if (view === "product") fitReceipt();
      });

      if (DEV) enableDevMode();
      poll();
    })
    .catch(function (err) {
      fatal(
        "Could not load products.json (" + err.message + "). " +
        "The kiosk must be served over HTTP — open http://localhost:8080, not the file directly."
      );
    });
})();
