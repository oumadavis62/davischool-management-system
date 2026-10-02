from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from starlette.datastructures import MutableHeaders
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import HTTPConnection


_TAB_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_TAB_PARAM = "ds_tab"


class DaviSchoolTabSessionMiddleware:
    """
    Keep login sessions isolated per browser tab.

    Each tab gets a random identifier in sessionStorage. That identifier is
    carried on navigation as a query parameter and selects a distinct signed
    session cookie. Because sessionStorage is tab-scoped, two tabs on the same
    Render origin can remain authenticated as different users.
    """

    def __init__(
        self,
        app,
        secret_key,
        max_age=60 * 60 * 12,
        https_only=False,
        same_site="lax",
    ):
        self.app = app
        self.secret_key = secret_key
        self.max_age = max_age
        self.https_only = https_only
        self.same_site = same_site

    @staticmethod
    def _tab_id(scope):
        query = scope.get("query_string", b"").decode("utf-8", "ignore")
        values = parse_qs(query, keep_blank_values=True).get(_TAB_PARAM, [])
        value = values[0] if values else ""
        return value if _TAB_RE.fullmatch(value or "") else ""

    @staticmethod
    def _cookie_name(tab_id):
        return "davischool_session_" + tab_id

    @staticmethod
    def _with_tab(location, tab_id):
        if not tab_id or not location or not location.startswith("/"):
            return location
        parts = urlsplit(location)
        query = parse_qs(parts.query, keep_blank_values=True)
        if _TAB_PARAM not in query:
            query[_TAB_PARAM] = [tab_id]
            query_text = urlencode(query, doseq=True)
            return urlunsplit(("", "", parts.path, query_text, parts.fragment))
        return location

    @staticmethod
    def _browser_script():
        return """<script>
(function () {
  try {
    var KEY = "davischool_tab_id";
    var NAV_KEY = "davischool_tab_navigation";
    var id = sessionStorage.getItem(KEY);

    function newTabId() {
      if (window.crypto && crypto.randomUUID) {
        return crypto.randomUUID().replace(/-/g, "");
      }
      return Date.now().toString(36) + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
    }

    var navigationType = "navigate";
    try {
      var nav = performance.getEntriesByType("navigation")[0];
      if (nav && nav.type) navigationType = nav.type;
    } catch (_) {}

    var internalNavigation = sessionStorage.getItem(NAV_KEY) === "1";
    sessionStorage.removeItem(NAV_KEY);

    // Keep the tab identity stable across server redirects and normal
    // navigation. Rotating the ID merely because a URL contains ds_tab can
    // silently create a brand-new empty session after POST/redirect flows
    // (MarkSheet, Marks Corrections, PDF/print, etc.).
    //
    // A duplicated tab may carry the same sessionStorage value, but preserving
    // the current tab ID is safer than destroying an authenticated session.
    // The server still keeps each explicitly established ds_tab cookie isolated.
    if (!id) {
      id = newTabId();
      sessionStorage.setItem(KEY, id);
    }

    function markInternalNavigation() {
      try { sessionStorage.setItem(NAV_KEY, "1"); } catch (_) {}
    }

    function addTab(value) {
      try {
        var u = new URL(value, window.location.origin);
        if (u.origin !== window.location.origin) return value;
        if (!u.searchParams.has("ds_tab")) u.searchParams.set("ds_tab", id);
        return u.pathname + (u.search ? u.search : "") + (u.hash ? u.hash : "");
      } catch (_) {
        return value;
      }
    }

    var currentUrl = new URL(window.location.href);
    var urlTabId = currentUrl.searchParams.get("ds_tab") || "";
    // The URL and sessionStorage must always refer to the same tab session.
    // This is especially important after a redirect or when a page was opened
    // in a new tab: a stale ds_tab in the URL must never cause this tab to use
    // another tab's authenticated cookie.
    if (urlTabId !== id) {
      currentUrl.searchParams.set("ds_tab", id);
      markInternalNavigation();
      window.location.replace(currentUrl.pathname + currentUrl.search + currentUrl.hash);
      return;
    }

    document.addEventListener("click", function (event) {
      var link = event.target && event.target.closest ? event.target.closest("a[href]") : null;
      if (!link) return;
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      var href = link.getAttribute("href");
      if (!href || href[0] === "#" || /^(mailto|tel|javascript):/i.test(href)) return;
      if (/^https?:/i.test(href) && !href.startsWith(window.location.origin)) return;
      link.setAttribute("href", addTab(href));
      if (link.target !== "_blank") markInternalNavigation();
    }, true);

    document.addEventListener("submit", function (event) {
      var form = event.target;
      if (!form || !form.action) return;
      var hidden = form.querySelector('input[name="ds_tab"]');
      if (!hidden) {
        hidden = document.createElement("input");
        hidden.type = "hidden";
        hidden.name = "ds_tab";
        form.appendChild(hidden);
      }
      hidden.value = id;
      form.action = addTab(form.action);
      markInternalNavigation();
    }, true);

    // Keep an open authenticated tab alive independently of clicks on its
    // dashboard tiles. The server idle timer is based on the tab session, so
    // a page that remains open must periodically refresh that session even
    // when the user is reading the page and has not navigated for a while.
    // This does not share sessions between tabs; each tab keeps its own
    // ds_tab cookie/session.
    var keepAliveTimer = null;
    function keepTabSessionAlive() {
      try {
        var u = new URL("/app/session-keepalive", window.location.origin);
        u.searchParams.set("ds_tab", id);
        fetch(u.pathname + u.search, {
          method: "GET",
          credentials: "same-origin",
          cache: "no-store",
          headers: {"X-DaviSchool-Keepalive": "1"}
        }).catch(function () {});
      } catch (_) {}
    }
    // Refresh well before the 15-minute inactivity window so a still-open
    // dashboard/tile never becomes a stale session merely because it was not
    // clicked during that period.
    keepAliveTimer = window.setInterval(keepTabSessionAlive, 4 * 60 * 1000);

    var originalFetch = window.fetch;
    if (originalFetch) {
      window.fetch = function (input, init) {
        try {
          if (typeof input === "string") input = addTab(input);
          else if (input && input.url) input = new Request(addTab(input.url), input);
        } catch (_) {}
        return originalFetch.call(this, input, init);
      };
    }

    var originalOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function (method, url) {
      try { url = addTab(url); } catch (_) {}
      return originalOpen.apply(this, arguments.length > 2 ? [method, url].concat([].slice.call(arguments, 2)) : [method, url]);
    };
  } catch (_) {}
})();
</script>"""

    async def __call__(self, scope, receive, send):
        if scope.get("type") not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        tab_id = self._tab_id(scope)
        scope["davischool_tab_id"] = tab_id

        session_cookie = self._cookie_name(tab_id) if tab_id else "session"
        session_app = SessionMiddleware(
            self.app,
            secret_key=self.secret_key,
            session_cookie=session_cookie,
            max_age=self.max_age,
            path="/",
            same_site=self.same_site,
            https_only=self.https_only,
        )

        async def send_wrapper(message):
            if message["type"] != "http.response.start":
                await send(message)
                return

            headers = MutableHeaders(scope=message)
            location = headers.get("location")
            if tab_id and location:
                headers["location"] = self._with_tab(location, tab_id)

            content_type = (headers.get("content-type") or "").lower()
            if tab_id and "text/html" in content_type:
                content_length = headers.get("content-length")
                if content_length is None:
                    # SessionMiddleware sends the response headers before the
                    # body. HTML injection is therefore handled below only for
                    # chunked/unknown-length responses.
                    pass

            await send(message)

        # When a tab id is present, preserve it on redirects. The browser-side
        # script is injected by wrapping response body messages separately.
        body_chunks = []
        html_response = {"value": False}

        async def capture_send(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                content_type = (headers.get("content-type") or "").lower()
                html_response["value"] = "text/html" in content_type
                location = headers.get("location")
                if tab_id and location:
                    headers["location"] = self._with_tab(location, tab_id)
                if html_response["value"]:
                    try:
                        del headers["content-length"]
                    except KeyError:
                        pass
                await send(message)
                return
            if message["type"] == "http.response.body" and html_response["value"]:
                body_chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    body = b"".join(body_chunks)
                    script = self._browser_script().encode("utf-8")
                    marker = b"</body>"
                    if marker in body.lower():
                        idx = body.lower().rfind(marker)
                        body = body[:idx] + script + body[idx:]
                    else:
                        body += script
                    await send({**message, "body": body, "more_body": False})
                return
            await send(message)

        await session_app(scope, receive, capture_send)
