(function () {
  const page = document.body.dataset.page || "";

  function initYearAndVersion() {
    var yearNodes = document.querySelectorAll("[data-year]");
    yearNodes.forEach(function (node) {
      node.textContent = String(new Date().getFullYear());
    });

    var versionNodes = document.querySelectorAll("[data-version]");
    versionNodes.forEach(function (node) {
      if (!node.textContent.trim()) {
        node.textContent = "v0.2.0";
      }
    });
  }

  function initPageTransition() {
    document.querySelectorAll("a[data-nav-transition]").forEach(function (link) {
      link.addEventListener("click", function (event) {
        if (
          event.defaultPrevented ||
          link.target === "_blank" ||
          event.metaKey ||
          event.ctrlKey ||
          event.shiftKey ||
          event.altKey
        ) {
          return;
        }

        var href = link.getAttribute("href");
        if (!href || href.startsWith("#") || href.startsWith("mailto:")) {
          return;
        }

        var destination = new URL(href, window.location.origin);
        if (destination.origin !== window.location.origin) {
          return;
        }

        event.preventDefault();
        document.body.classList.add("page-leave");
        setTimeout(function () {
          window.location.href = destination.href;
        }, 170);
      });
    });
  }

  function initCopyButtons() {
    document.querySelectorAll("[data-copy-target]").forEach(function (button) {
      button.addEventListener("click", async function () {
        var selector = button.getAttribute("data-copy-target");
        var source = selector ? document.querySelector(selector) : null;
        if (!source) {
          return;
        }

        try {
          await navigator.clipboard.writeText(source.textContent || "");
          var previous = button.textContent;
          button.textContent = "Copied";
          setTimeout(function () {
            button.textContent = previous;
          }, 1300);
        } catch (error) {
          button.textContent = "Copy failed";
          setTimeout(function () {
            button.textContent = "Copy";
          }, 1300);
        }
      });
    });
  }

  function startReveals() {
    if (!window.gsap || !window.ScrollTrigger) {
      document.querySelectorAll(".reveal").forEach(function (node) {
        node.dataset.revealInit = "1";
        node.style.opacity = "1";
        node.style.transform = "none";
      });
      return;
    }

    window.gsap.registerPlugin(window.ScrollTrigger);
    document.querySelectorAll(".reveal").forEach(function (node, idx) {
      if (node.dataset.revealInit === "1") {
        return;
      }
      node.dataset.revealInit = "1";
      window.gsap.fromTo(
        node,
        { autoAlpha: 0, y: 26 },
        {
          autoAlpha: 1,
          y: 0,
          duration: 0.85,
          ease: "power2.out",
          delay: idx * 0.03,
          scrollTrigger: {
            trigger: node,
            start: "top 85%",
            once: true
          }
        }
      );
    });
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function endpointPrice(endpoint) {
    function centsText(cents) {
      if (typeof cents !== "number" || Number.isNaN(cents)) {
        return "";
      }
      return " / " + cents.toFixed(1) + "¢";
    }

    if (endpoint.price_type === "flat") {
      return (endpoint.price_sats || 0) + " sats" + centsText(endpoint.price_usd_cents);
    }

    if (endpoint.price_type === "per_model") {
      var models = endpoint.models || {};
      return Object.keys(models)
        .map(function (model) {
          var modelConfig = models[model];
          var sats = 0;
          var cents;
          var maxOutputTokens;

          if (modelConfig && typeof modelConfig === "object") {
            sats = modelConfig.price_sats || 0;
            cents = modelConfig.price_usd_cents;
            maxOutputTokens = modelConfig.max_output_tokens;
          } else {
            sats = modelConfig || 0;
          }

          var line = model + ": " + sats + " sats" + centsText(cents);
          if (typeof maxOutputTokens === "number") {
            line += " (max_out " + maxOutputTokens + ")";
          }
          return line;
        })
        .join(" | ");
    }

    return "n/a";
  }

  async function loadCatalog() {
    if (page !== "catalog") {
      return;
    }

    var wrap = document.querySelector("#catalog-list");
    if (!wrap) {
      return;
    }

    try {
      var response = await fetch("/api/catalog");
      if (!response.ok) {
        throw new Error("Catalog request failed");
      }

      var payload = await response.json();
      var html = "";
      var btcMeta = document.querySelector("#btc-price-meta");
      if (btcMeta) {
        if (typeof payload.btc_usd === "number") {
          var btcUsd = payload.btc_usd;
          var updatedText = payload.btc_usd_updated_at
            ? " | Updated: " + payload.btc_usd_updated_at
            : "";
          btcMeta.textContent =
            "BTC/USD: $" + btcUsd.toLocaleString(undefined, { maximumFractionDigits: 2 }) + updatedText;
        } else {
          btcMeta.textContent = "BTC/USD unavailable. Showing sats as source of truth.";
        }
      }

      var apis = payload.apis || {};
      Object.keys(apis).forEach(function (apiName) {
        var api = apis[apiName] || {};
        var endpoints = (api.endpoints || [])
          .map(function (endpoint) {
            var description = endpoint.description || "";
            if (typeof endpoint.max_request_bytes === "number") {
              description += (description ? " | " : "") + "max " + endpoint.max_request_bytes + " bytes";
            }
            return [
              '<li class="endpoint">',
              '<div class="line">',
              "<code>" + escapeHtml(endpoint.method || "POST") + " " + escapeHtml(endpoint.path || "") + "</code>",
              '<span class="price">' + escapeHtml(endpointPrice(endpoint)) + "</span>",
              "</div>",
              "<p>" + escapeHtml(description) + "</p>",
              "</li>"
            ].join("");
          })
          .join("");

        html += [
          '<article class="api-card reveal">',
          "<h3>" + escapeHtml(api.name || apiName || "API") + "</h3>",
          '<span class="api-badge">' + escapeHtml(apiName || "") + "</span>",
          '<ul class="endpoint-list">' + endpoints + "</ul>",
          "</article>"
        ].join("");
      });

      if (!html) {
        html = '<div class="status-note">No APIs are currently configured.</div>';
      }

      wrap.innerHTML = html;
      startReveals();
    } catch (error) {
      wrap.innerHTML = '<div class="status-note">Failed to load catalog. Refresh and try again.</div>';
    }
  }

  initYearAndVersion();
  initPageTransition();
  initCopyButtons();
  startReveals();
  loadCatalog();
})();
