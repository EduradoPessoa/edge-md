/* ==========================================================================
   Leitor MD — runtime do preview
   Roda dentro do QWebEngineView. Responsabilidades:
     * trocar de tema sem re-renderizar (habilita/desabilita a folha de estilo);
     * botão "Copiar" nos blocos de código;
     * envolver tabelas num contêiner que rola na horizontal;
     * renderizar Mermaid (diagramas) e KaTeX (matemática);
     * sincronizar o scroll com o editor usando data-line;
     * barra de progresso de leitura.

   Toda comunicação com o Python passa pelo QWebChannel. Se o canal não estiver
   disponível, o preview continua funcionando — só a sincronia de scroll do
   preview para o editor fica desligada.
   ========================================================================== */

(function () {
  "use strict";

  var CFG = window.__MD_CONFIG__ || {};
  var bridge = null;
  var mermaidReady = false;
  var mermaidSeq = 0;

  // Evita laço infinito: quando o Python manda rolar, não reportamos de volta.
  //
  // O temporizador é uma variável separada, e não uma propriedade pendurada em
  // `suppressReport`. Aquele era um bug: `suppressReport` é um booleano, e em
  // modo estrito (o IIFE abaixo) criar propriedade num primitivo lança
  // TypeError — a exceção abortava o resto da função, matando a sincronia de
  // rolagem e os cliques em âncora.
  var suppressReport = false;
  var suppressTimer = null;
  var reportTimer = null;
  var lastReportedLine = -1;

  function suppressReporting(ms) {
    suppressReport = true;
    clearTimeout(suppressTimer);
    suppressTimer = setTimeout(function () {
      suppressReport = false;
    }, ms);
  }

  // ------------------------------------------------------------------
  // Utilidades
  // ------------------------------------------------------------------

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function $$(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function toast(message, ms) {
    var el = $("#toast");
    if (!el) return;
    el.textContent = message;
    el.classList.add("is-visible");
    clearTimeout(el._timer);
    el._timer = setTimeout(function () {
      el.classList.remove("is-visible");
    }, ms || 1600);
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      if (!src) {
        reject(new Error("sem origem"));
        return;
      }
      var tag = document.createElement("script");
      tag.src = src;
      tag.onload = function () { resolve(); };
      tag.onerror = function () { reject(new Error("falha ao carregar " + src)); };
      document.head.appendChild(tag);
    });
  }

  function resolvedTheme() {
    return document.documentElement.getAttribute("data-theme") || "dark";
  }

  // ------------------------------------------------------------------
  // Tema
  // ------------------------------------------------------------------

  function applyTheme(name) {
    if (name !== "light" && name !== "dark") name = "dark";
    document.documentElement.setAttribute("data-theme", name);

    $$("style[data-theme-sheet]").forEach(function (sheet) {
      sheet.disabled = sheet.getAttribute("data-theme-sheet") !== name;
    });

    // Mermaid precisa das cores em tempo de renderização, então refaz.
    if (mermaidReady) {
      mermaidReady = false;
      $$(".diagram-block").forEach(function (block) {
        block.classList.remove("is-rendered", "is-error");
        var rendered = $(".mermaid-rendered", block);
        if (rendered) rendered.remove();
      });
      renderMermaid();
    }
    return name;
  }

  // ------------------------------------------------------------------
  // Botões de copiar
  // ------------------------------------------------------------------

  function setupCopyButtons() {
    $$("[data-copy]").forEach(function (button) {
      if (button._wired) return;
      button._wired = true;

      button.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();

        var block = button.closest(".code-block");
        var codeEl = block ? $("code", block) : null;
        var text = codeEl ? codeEl.innerText : "";
        if (!text) return;

        var done = function () {
          button.textContent = "Copiado";
          button.classList.add("is-copied");
          setTimeout(function () {
            button.textContent = "Copiar";
            button.classList.remove("is-copied");
          }, 1400);
        };

        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done, function () {
            fallbackCopy(text, done);
          });
        } else {
          fallbackCopy(text, done);
        }
      });
    });
  }

  function fallbackCopy(text, done) {
    // navigator.clipboard exige contexto seguro; sob file:// pode não existir.
    var area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.top = "-1000px";
    document.body.appendChild(area);
    area.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    document.body.removeChild(area);
    if (ok) {
      done();
    } else {
      toast("Não foi possível copiar automaticamente");
    }
  }

  // ------------------------------------------------------------------
  // Tabelas e checkboxes
  // ------------------------------------------------------------------

  function wrapTables() {
    $$("table").forEach(function (table) {
      if (table.parentElement && table.parentElement.classList.contains("table-wrap")) return;
      var wrap = document.createElement("div");
      wrap.className = "table-wrap";
      table.parentNode.insertBefore(wrap, table);
      wrap.appendChild(table);
    });
  }

  function freezeCheckboxes() {
    // O preview é somente leitura: marcar aqui não alteraria o arquivo e
    // criaria a impressão falsa de que a tarefa foi persistida.
    $$('li.task-list-item input[type="checkbox"]').forEach(function (box) {
      box.disabled = true;
      box.setAttribute("aria-disabled", "true");
    });
  }

  // ------------------------------------------------------------------
  // Matemática (KaTeX)
  // ------------------------------------------------------------------

  function renderMath() {
    if (!CFG.math) return;

    var nodes = $$(".math");
    if (!nodes.length) return;

    loadScript(CFG.katexSrc)
      .then(function () {
        if (!window.katex) return;
        nodes.forEach(function (node) {
          if (node.dataset.katexDone) return;
          var source = node.textContent || "";
          // O dollarmath emite <span class="math inline"> ou
          // <div class="math block">, então a classe decide o modo.
          var display =
            node.classList.contains("block") || node.tagName === "DIV";
          try {
            window.katex.render(source, node, {
              displayMode: display,
              throwOnError: false,
              strict: false,
              trust: false
            });
            node.dataset.katexDone = "1";
          } catch (err) {
            // Fórmula inválida: mantém o LaTeX cru visível em vez de sumir.
            node.dataset.katexDone = "1";
          }
        });
      })
      .catch(function () {
        // Sem KaTeX instalado: as fórmulas aparecem como texto. Silencioso de
        // propósito, para não poluir o preview com erro de dependência.
      });
  }

  // ------------------------------------------------------------------
  // Diagramas (Mermaid)
  // ------------------------------------------------------------------

  function renderMermaid() {
    if (!CFG.mermaid || mermaidReady) return;

    var blocks = $$('.diagram-block[data-diagram="mermaid"]');
    if (!blocks.length) return;

    mermaidReady = true;

    loadScript(CFG.mermaidSrc)
      .then(function () {
        if (!window.mermaid) throw new Error("mermaid ausente");

        window.mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: resolvedTheme() === "dark" ? "dark" : "default",
          fontFamily: "Segoe UI, system-ui, sans-serif"
        });

        var jobs = blocks.map(function (block) {
          var sourceEl = $(".mermaid-source", block);
          var code = sourceEl ? sourceEl.textContent : "";
          if (!code.trim()) return Promise.resolve();

          var id = "mermaid-" + (++mermaidSeq);
          var attempt = window.mermaid.render(id, code);

          // mermaid v10+ devolve Promise; versões antigas devolvem callback.
          return Promise.resolve(attempt).then(function (result) {
            var svg = result && result.svg ? result.svg : result;
            var host = document.createElement("div");
            host.className = "mermaid-rendered";
            host.innerHTML = svg;
            block.appendChild(host);
            block.classList.add("is-rendered");
          });
        });

        return Promise.all(jobs);
      })
      .catch(function (err) {
        mermaidReady = false;
        blocks.forEach(function (block) {
          if (!block.classList.contains("is-rendered")) {
            block.classList.add("is-error");
          }
        });
        // O código-fonte do diagrama permanece visível, então o usuário não
        // perde informação — só não vê o desenho.
        console.warn("Mermaid indisponível:", err && err.message);
      });
  }

  // ------------------------------------------------------------------
  // Barra de progresso
  // ------------------------------------------------------------------

  function setupProgress() {
    if ($(".progress-bar")) return;
    var bar = document.createElement("div");
    bar.className = "progress-bar";
    document.body.appendChild(bar);

    var update = function () {
      var doc = document.documentElement;
      var max = doc.scrollHeight - doc.clientHeight;
      var ratio = max > 0 ? doc.scrollTop / max : 0;
      bar.style.width = Math.min(100, Math.max(0, ratio * 100)) + "%";
    };

    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    update();
  }

  // ------------------------------------------------------------------
  // Sincronia de scroll
  // ------------------------------------------------------------------

  function lineAnchors() {
    // Ordenados por posição na página: a busca binária abaixo depende disso.
    return $$("[data-line]").sort(function (a, b) {
      return a.getBoundingClientRect().top - b.getBoundingClientRect().top;
    });
  }

  function scrollToLine(line, smooth) {
    var anchors = lineAnchors();
    if (!anchors.length) return;

    var target = null;
    for (var i = 0; i < anchors.length; i++) {
      var value = parseInt(anchors[i].getAttribute("data-line"), 10);
      if (!isNaN(value) && value <= line) {
        target = anchors[i];
      } else {
        break;
      }
    }
    if (!target) target = anchors[0];

    suppressReporting(smooth ? 420 : 90);
    target.scrollIntoView({
      behavior: smooth ? "smooth" : "auto",
      block: "start"
    });
  }

  function topLine() {
    var anchors = lineAnchors();
    if (!anchors.length) return 1;
    var best = parseInt(anchors[0].getAttribute("data-line"), 10) || 1;
    for (var i = 0; i < anchors.length; i++) {
      var top = anchors[i].getBoundingClientRect().top;
      if (top <= 8) {
        best = parseInt(anchors[i].getAttribute("data-line"), 10) || best;
      } else {
        break;
      }
    }
    return best;
  }

  function reportScroll() {
    if (suppressReport || !bridge) return;
    var line = topLine();
    if (line === lastReportedLine) return;
    lastReportedLine = line;
    try {
      bridge.onScrolled(line);
    } catch (err) {
      /* canal caiu; sincronia do preview para o editor fica desligada */
    }
  }

  function setupScrollSync() {
    window.addEventListener(
      "scroll",
      function () {
        clearTimeout(reportTimer);
        reportTimer = setTimeout(reportScroll, 120);
      },
      { passive: true }
    );
  }

  // ------------------------------------------------------------------
  // Áreas de clique: links externos e âncoras internas
  // ------------------------------------------------------------------

  function setupLinkHandling() {
    document.addEventListener("click", function (event) {
      var link = event.target.closest && event.target.closest("a[href]");
      if (!link) return;
      var href = link.getAttribute("href") || "";

      // Âncora interna: rolagem suave em vez de navegação.
      if (href.charAt(0) === "#") {
        var target = document.getElementById(href.slice(1));
        if (target) {
          event.preventDefault();
          suppressReporting(420);
          target.scrollIntoView({ behavior: "smooth", block: "start" });
        }
        return;
      }

      // Links http(s) e arquivos são decididos no lado Python
      // (acceptNavigationRequest). Aqui só evitamos que o Chromium troque o
      // documento inteiro, o que destruiria o preview.
      if (/^(https?:|mailto:|file:)/i.test(href)) {
        event.preventDefault();
        if (bridge && bridge.onLinkActivated) {
          try { bridge.onLinkActivated(href); } catch (err) { /* ignora */ }
        }
      }
    });
  }

  // ------------------------------------------------------------------
  // Duplo clique: pedido para editar
  // ------------------------------------------------------------------

  function setupEditShortcut() {
    document.addEventListener("dblclick", function (event) {
      // Duplo clique costuma selecionar uma palavra; no contexto de leitura,
      // o gesto mais útil é abrir o editor.
      var selection = window.getSelection();
      if (selection && !selection.isCollapsed) return;

      // Um duplo clique sobre um link tem outro significado: não sequestrar.
      if (event.target.closest && event.target.closest("a[href]")) return;

      if (bridge && bridge.onEditRequested) {
        try { bridge.onEditRequested(); } catch (err) { /* ignora */ }
      }
    });
  }

  // ------------------------------------------------------------------
  // Ponte com o Python (QWebChannel)
  // ------------------------------------------------------------------

  function setupBridge() {
    // `qt` só existe quando a página foi criada pelo QWebEnginePage com um
    // WebChannel registrado. No HTML exportado, e nas páginas internas de
    // exportação, ele não existe — e tocar nele geraria um erro de JS inútil.
    if (typeof QWebChannel === "undefined" || typeof qt === "undefined") return;
    try {
      new QWebChannel(qt.webChannelTransport, function (channel) {
        bridge = channel.objects.bridge;
        if (bridge && bridge.onReady) {
          try { bridge.onReady(); } catch (err) { /* ignora */ }
        }
      });
    } catch (err) {
      console.warn("QWebChannel indisponível:", err && err.message);
    }
  }

  // ------------------------------------------------------------------
  // Inicialização
  // ------------------------------------------------------------------

  function boot() {
    applyTheme(resolvedTheme());
    setupProgress();

    wrapTables();
    freezeCheckboxes();
    setupCopyButtons();
    setupLinkHandling();
    setupScrollSync();
    setupEditShortcut();

    // A matemática vem antes do Mermaid: é mais leve e costuma ser o caso
    // mais comum em notas técnicas.
    renderMath();
    renderMermaid();

    setupBridge();
  }

  // API chamada pelo Python via runJavaScript.
  window.setTheme = applyTheme;
  window.scrollToLine = scrollToLine;
  window.getTopLine = topLine;
  window.refreshBlocks = function () {
    wrapTables();
    freezeCheckboxes();
    setupCopyButtons();
    renderMath();
    renderMermaid();
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
