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

  function initCopyButtons(root) {
    var scope = root || document;
    scope.querySelectorAll("[data-copy-target]").forEach(function (button) {
      if (button.dataset.copyBound === "1") {
        return;
      }
      button.dataset.copyBound = "1";

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

  function slugify(value) {
    return String(value)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  }

  function centsText(cents) {
    if (typeof cents !== "number" || Number.isNaN(cents)) {
      return "";
    }
    return cents.toFixed(1) + "\u00a2";
  }

  function endpointPriceFlat(endpoint) {
    var sats = (endpoint.price_sats || 0) + " sats";
    var cents = centsText(endpoint.price_usd_cents);
    return cents ? sats + " / " + cents : sats;
  }

  function buildModelTable(endpoint) {
    var models = endpoint.models || {};
    var keys = Object.keys(models);
    if (!keys.length) {
      return '<span class="status-note">No model prices configured.</span>';
    }

    var rows = keys
      .map(function (model) {
        var cfg = models[model];
        var sats = 0;
        var cents;
        if (cfg && typeof cfg === "object") {
          sats = cfg.price_sats || 0;
          cents = cfg.price_usd_cents;
        } else {
          sats = cfg || 0;
        }

        return [
          "<tr>",
          "<td>" + escapeHtml(model) + "</td>",
          '<td><span class="sats-value">' + escapeHtml(sats) + "</span></td>",
          "<td>" + (centsText(cents) || "-") + "</td>",
          "</tr>"
        ].join("");
      })
      .join("");

    return [
      '<div class="model-table-wrap">',
      '<table class="model-table">',
      "<thead><tr><th>Model</th><th>Sats</th><th>USD</th></tr></thead>",
      "<tbody>" + rows + "</tbody>",
      "</table>",
      "</div>"
    ].join("");
  }

  function endpointRoute(apiName, endpointPath) {
    var path = endpointPath || "";
    if (!path) {
      return "/" + apiName;
    }
    if (path.charAt(0) === "/") {
      return "/" + apiName + path;
    }
    return "/" + apiName + "/" + path;
  }

  function sampleJsonBody(endpointPath) {
    if (endpointPath === "/v1/chat/completions") {
      return {
        model: "gpt-4o-mini",
        messages: [{ role: "user", content: "Say hello in five words." }]
      };
    }

    if (endpointPath === "/v1/images/generations") {
      return {
        model: "gpt-image-1-mini",
        prompt: "A neon bitcoin logo over brushed steel.",
        size: "1024x1024"
      };
    }

    if (endpointPath === "/v1/audio/speech") {
      return {
        model: "tts-1",
        voice: "alloy",
        input: "Hello from the Lightning Network."
      };
    }

    if (endpointPath === "/v1/embeddings") {
      return {
        model: "text-embedding-3-small",
        input: "Lightning invoices and preimages"
      };
    }

    return {
      model: "gpt-4o-mini"
    };
  }

  function buildEndpointSnippets(apiName, endpointPath) {
    var route = endpointRoute(apiName, endpointPath);
    var isMultipart = endpointPath === "/v1/audio/transcriptions";

    if (isMultipart) {
      return {
        curl: [
          'API="https://alittlebitofmoney.com"',
          "",
          'STEP1=$(curl -s -X POST "$API' + route + '" -F "model=whisper-1" -F "file=@sample.mp3")',
          "",
          'INVOICE=$(echo "$STEP1" | jq -r \'.invoice\')',
          'echo "$INVOICE"',
          '# Pay with your wallet and get preimage',
          'read -r -p "Preimage: " PREIMAGE',
          "",
          'curl -s "$API/redeem?preimage=$PREIMAGE" | jq .'
        ].join("\n"),
        python: [
          "import requests",
          "",
          'API = "https://alittlebitofmoney.com"',
          'route = "' + route + '"',
          "",
          'with open("sample.mp3", "rb") as audio_file:',
          "    step1 = requests.post(",
          "        f\"{API}{route}\",",
          '        data={"model": "whisper-1"},',
          '        files={"file": audio_file},',
          "    )",
          "",
          'invoice = step1.json()["invoice"]',
          'print("Pay this invoice with your wallet:")',
          "print(invoice)",
          "",
          'preimage = input("Preimage: ").strip()',
          'result = requests.get(f"{API}/redeem", params={"preimage": preimage})',
          "print(result.json())"
        ].join("\n"),
        javascript: [
          'const API = "https://alittlebitofmoney.com";',
          'const route = "' + route + '";',
          "",
          "const form = new FormData();",
          'form.append("model", "whisper-1");',
          "// audioFile should be a Blob/File from your app",
          'form.append("file", audioFile, "sample.mp3");',
          "",
          "const step1 = await fetch(`${API}${route}`, {",
          '  method: "POST",',
          "  body: form,",
          "});",
          "",
          "const { invoice } = await step1.json();",
          'console.log("Pay this invoice with your wallet:", invoice);',
          "",
          'const preimage = prompt("Preimage:");',
          'const result = await fetch(`${API}/redeem?preimage=${preimage}`);',
          "console.log(await result.json());"
        ].join("\n")
      };
    }

    var requestBody = sampleJsonBody(endpointPath);
    var compactJson = JSON.stringify(requestBody).replace(/'/g, "'\"'\"'");
    var prettyJson = JSON.stringify(requestBody, null, 2);

    return {
      curl: [
        'API="https://alittlebitofmoney.com"',
        "",
        'STEP1=$(curl -s -X POST "$API' + route + '" -H "Content-Type: application/json" -d \'' + compactJson + '\')',
        "",
        'INVOICE=$(echo "$STEP1" | jq -r \'.invoice\')',
        'echo "$INVOICE"',
        '# Pay with your wallet and get preimage',
        'read -r -p "Preimage: " PREIMAGE',
        "",
        'curl -s "$API/redeem?preimage=$PREIMAGE" | jq .'
      ].join("\n"),
      python: [
        "import requests",
        "",
        'API = "https://alittlebitofmoney.com"',
        'route = "' + route + '"',
        "payload = " + prettyJson,
        "",
        "step1 = requests.post(f\"{API}{route}\", json=payload)",
        'invoice = step1.json()["invoice"]',
        'print("Pay this invoice with your wallet:")',
        "print(invoice)",
        "",
        'preimage = input("Preimage: ").strip()',
        'result = requests.get(f"{API}/redeem", params={"preimage": preimage})',
        "print(result.json())"
      ].join("\n"),
      javascript: [
        'const API = "https://alittlebitofmoney.com";',
        'const route = "' + route + '";',
        "",
        "const payload = " + prettyJson + ";",
        "",
        "const step1 = await fetch(`${API}${route}`, {",
        '  method: "POST",',
        '  headers: { "Content-Type": "application/json" },',
        "  body: JSON.stringify(payload),",
        "});",
        "",
        "const { invoice } = await step1.json();",
        'console.log("Pay this invoice with your wallet:", invoice);',
        "",
        'const preimage = prompt("Preimage:");',
        'const result = await fetch(`${API}/redeem?preimage=${preimage}`);',
        "console.log(await result.json());"
      ].join("\n")
    };
  }

  function buildCodeCard(label, code, codeId) {
    return [
      '<article class="code-card">',
      '<div class="code-head"><span>' + escapeHtml(label) + '</span><button class="copy-btn" data-copy-target="#' + escapeHtml(codeId) + '">Copy</button></div>',
      '<pre><code id="' + escapeHtml(codeId) + '">' + escapeHtml(code) + "</code></pre>",
      "</article>"
    ].join("");
  }

  function buildEndpointExamples(apiName, endpoint, endpointIndex) {
    var snippets = buildEndpointSnippets(apiName, endpoint.path || "");
    var keyBase = slugify(apiName + "-" + (endpoint.path || "endpoint") + "-" + endpointIndex);

    return [
      '<div class="endpoint-examples">',
      '<p class="endpoint-examples-title">Code Examples</p>',
      '<div class="grid cols-3 endpoint-example-grid">',
      buildCodeCard("curl", snippets.curl, "code-" + keyBase + "-curl"),
      buildCodeCard("python", snippets.python, "code-" + keyBase + "-python"),
      buildCodeCard("javascript", snippets.javascript, "code-" + keyBase + "-javascript"),
      "</div>",
      "</div>"
    ].join("");
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

      var apisInput = payload.apis || {};
      var apiEntries = [];
      if (Array.isArray(apisInput)) {
        apiEntries = apisInput.map(function (api) {
          return {
            apiName: api.api_name || api.name || "api",
            api: api || {}
          };
        });
      } else {
        apiEntries = Object.keys(apisInput).map(function (apiName) {
          return {
            apiName: apiName,
            api: apisInput[apiName] || {}
          };
        });
      }

      apiEntries.forEach(function (entry) {
        var apiName = entry.apiName;
        var api = entry.api;
        var seenEndpoints = {};
        var uniqueEndpoints = [];

        (api.endpoints || []).forEach(function (endpoint) {
          var key = String((endpoint.method || "POST").toUpperCase()) + "|" + String(endpoint.path || "");
          if (seenEndpoints[key]) {
            return;
          }
          seenEndpoints[key] = true;
          uniqueEndpoints.push(endpoint);
        });

        var endpoints = uniqueEndpoints
          .map(function (endpoint, idx) {
            var description = endpoint.description || "";
            var fullPath = endpointRoute(apiName, endpoint.path || "");
            var pricingHtml;
            if (endpoint.price_type === "per_model") {
              pricingHtml = buildModelTable(endpoint);
            } else {
              pricingHtml = '<span class="price">' + escapeHtml(endpointPriceFlat(endpoint)) + "</span>";
            }

            return [
              '<li class="endpoint">',
              '<div class="line">',
              "<code>" + escapeHtml(endpoint.method || "POST") + " " + escapeHtml(fullPath) + "</code>",
              endpoint.price_type !== "per_model" ? pricingHtml : "",
              "</div>",
              description ? "<p>" + escapeHtml(description) + "</p>" : "",
              endpoint.price_type === "per_model" ? pricingHtml : "",
              buildEndpointExamples(apiName, endpoint, idx),
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
      initCopyButtons(wrap);
      startReveals();
    } catch (error) {
      var btcMetaErr = document.querySelector("#btc-price-meta");
      if (btcMetaErr) {
        btcMetaErr.style.display = "none";
      }
      wrap.innerHTML = '<div class="status-note">Failed to load catalog. Refresh and try again.</div>';
    }
  }

  initYearAndVersion();
  initPageTransition();
  initCopyButtons();
  startReveals();
  loadCatalog();
})();
