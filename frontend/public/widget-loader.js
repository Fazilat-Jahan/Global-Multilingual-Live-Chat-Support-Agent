/*!
 * Support Chat Widget Loader (spec 5.1)
 *
 * Embeddable, one-script loader that creates and manages a sandboxed iframe
 * pointing at the widget page (/widget), with a floating launcher button, a
 * responsive mobile full-screen mode, and a postMessage-based open/close
 * protocol (origin-validated; no sensitive data crosses the boundary).
 *
 * Usage — minimal (auto-detects widget host from the script's own origin):
 *   <script src="https://<widget-host>/widget-loader.js"></script>
 *
 * Usage — explicit config:
 *   <script src="https://<widget-host>/widget-loader.js"
 *           data-host="https://<widget-host>"
 *           data-tenant="default"></script>
 *
 * Usage — pre-script config object:
 *   window.SupportChatConfig = {
 *     host: "https://<widget-host>",
 *     tenant: "default"
 *   };
 *   <script src="/widget-loader.js"></script>
 *
 * Public API (available after the script runs):
 *   window.SupportChat.open()
 *   window.SupportChat.close()
 *   window.SupportChat.toggle()
 */
(function () {
  "use strict";

  if (window.SupportChat) return; // idempotent

  var doc = document;
  var win = window;
  var scriptEl = doc.currentScript;
  var config = win.SupportChatConfig || {};

  function dataAttr(name) {
    return scriptEl ? scriptEl.getAttribute("data-" + name) : null;
  }

  // Widget host defaults to the origin this loader was served from; the
  // iframe src is <host>/widget?tenant=<tenant>. In production the widget
  // host, the loader script, and the iframe target are all the same origin.
  var host =
    config.host ||
    dataAttr("host") ||
    (scriptEl && scriptEl.src ? new URL(scriptEl.src).origin : null) ||
    win.location.origin;
  host = host.replace(/\/+$/, "");

  var tenant = config.tenant || dataAttr("tenant") || "default";
  var widgetOrigin = new URL(host).origin;

  // ---------- CSS (injected so the host page stays untouched) ----------
  var css = doc.createElement("style");
  css.textContent =
    ".sc-launcher{" +
    "position:fixed;bottom:20px;right:20px;width:56px;height:56px;" +
    "border-radius:50%;background:#3b6df0;color:#fff;border:none;" +
    "font-size:24px;cursor:pointer;box-shadow:0 10px 25px rgba(0,0,0,.2);" +
    "z-index:2147483600;display:flex;align-items:center;justify-content:center;" +
    "transition:transform .15s ease}" +
    ".sc-launcher:hover{transform:scale(1.05)}" +
    ".sc-frame{" +
    "position:fixed;bottom:88px;right:20px;width:400px;height:600px;" +
    "border:none;border-radius:16px;box-shadow:0 20px 50px rgba(0,0,0,.25);" +
    "z-index:2147483500;display:none;background:#fff}" +
    ".sc-frame.sc-open{display:block}" +
    ".sc-mobile-overlay{" +
    "position:fixed;top:8px;right:12px;width:40px;height:40px;" +
    "border-radius:50%;background:rgba(0,0,0,.55);color:#fff;border:none;" +
    "font-size:22px;cursor:pointer;z-index:2147483700;display:none;" +
    "align-items:center;justify-content:center}" +
    "@media(max-width:767px){" +
    ".sc-frame.sc-open{width:100vw;height:100vh;max-width:none;max-height:none;" +
    "inset:0;bottom:0;right:0;border-radius:0}" +
    ".sc-launcher{display:none}" +
    ".sc-mobile-overlay{display:flex}" +
    ".sc-frame:not(.sc-open)~.sc-mobile-overlay{display:none}}";
  doc.head.appendChild(css);

  // ---------- Launcher button ----------
  var launcher = doc.createElement("button");
  launcher.className = "sc-launcher";
  launcher.setAttribute("aria-label", "Open support chat");
  launcher.setAttribute("type", "button");
  launcher.textContent = "\uD83D\uDCAC"; // 💬
  doc.body.appendChild(launcher);

  // ---------- iframe ----------
  var frame = doc.createElement("iframe");
  frame.id = "support-chat-frame";
  frame.className = "sc-frame";
  frame.title = "Support chat";
  // Spec 5.1 security isolation: sandboxed iframe with the same-origin
  // allowlist so the widget's localStorage-based session works; forms and
  // popups are also permitted since the widget may open links.
  frame.setAttribute("sandbox", "allow-scripts allow-same-origin allow-forms allow-popups");
  frame.setAttribute("allow", "clipboard-write");
  frame.src = host + "/widget?tenant=" + encodeURIComponent(tenant);
  doc.body.appendChild(frame);

  // ---------- Mobile close overlay ----------
  var overlay = doc.createElement("button");
  overlay.className = "sc-mobile-overlay";
  overlay.setAttribute("aria-label", "Close support chat");
  overlay.setAttribute("type", "button");
  overlay.textContent = "\u2715"; // ✕
  doc.body.appendChild(overlay);

  // ---------- Open/close state ----------
  var open = false;

  function setOpen(value) {
    open = !!value;
    if (open) {
      frame.classList.add("sc-open");
      launcher.textContent = "\u2715"; // ✕
      launcher.setAttribute("aria-label", "Close support chat");
    } else {
      frame.classList.remove("sc-open");
      launcher.textContent = "\uD83D\uDCAC"; // 💬
      launcher.setAttribute("aria-label", "Open support chat");
    }
    try {
      frame.contentWindow.postMessage(
        { source: "support-chat-host", type: open ? "open" : "close" },
        widgetOrigin
      );
    } catch (_) {
      /* iframe may not be ready yet */
    }
  }

  launcher.addEventListener("click", function () {
    setOpen(!open);
  });
  overlay.addEventListener("click", function () {
    setOpen(false);
  });

  // ---------- postMessage protocol (spec 5.1) ----------
  // Host ← widget: { source: "support-chat-widget", type: "ready"|"close" }
  // Host → widget: { source: "support-chat-host",    type: "open"|"close"  }
  // Origin-validated on receive; no sensitive data crosses the boundary.
  win.addEventListener("message", function (event) {
    if (event.origin !== widgetOrigin) return;
    var data = event.data;
    if (!data || data.source !== "support-chat-widget") return;
    if (data.type === "close") setOpen(false);
  });

  // ---------- Public API ----------
  win.SupportChat = {
    open: function () {
      setOpen(true);
    },
    close: function () {
      setOpen(false);
    },
    toggle: function () {
      setOpen(!open);
    },
  };
})();
