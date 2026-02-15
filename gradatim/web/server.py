"""
HTTP server for the Gradatim web frontend.

Built entirely on Python's stdlib http.server. Uses ThreadingHTTPServer
for concurrent request handling. Serves static files and handles JSON API
endpoints for jobs, invites, compute config, and status.
"""

import json
import logging
import mimetypes
import os
import re
import socketserver
import threading
import time
import http.server
import http.cookies
import urllib.parse

from .store import Store

logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Handle each request in a new thread so one slow request can't block all others."""
    daemon_threads = True
    allow_reuse_address = True


def _read_static(filename: str) -> bytes | None:
    """Read a file from the static directory."""
    path = os.path.join(STATIC_DIR, filename)
    # Prevent directory traversal
    real = os.path.realpath(path)
    if not real.startswith(os.path.realpath(STATIC_DIR)):
        return None
    if not os.path.isfile(real):
        return None
    with open(real, "rb") as f:
        return f.read()


def _guess_content_type(filename: str) -> str:
    ct, _ = mimetypes.guess_type(filename)
    return ct or "application/octet-stream"


def _format_time(ts: float) -> str:
    """Format a unix timestamp as a human-readable string."""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def _make_handler(store: Store, agent=None):
    """
    Create a request handler class bound to the given store and agent.

    We use a closure so the handler can access shared state without globals.
    """

    class Handler(http.server.BaseHTTPRequestHandler):

        # Suppress default stderr logging
        def log_message(self, format, *args):
            logger.debug(format, *args)

        # --- Helpers ---

        def _send_json(self, data, status=200):
            body = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str, status=200):
            body = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def _send_static(self, filename: str):
            data = _read_static(filename)
            if data is None:
                self._send_404()
                return
            ct = _guess_content_type(filename)
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=3600")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)

        def _send_404(self):
            self._send_html(_page_404(), 404)

        def _send_redirect(self, location: str):
            self.send_response(303)
            self.send_header("Location", location)
            self.send_header("Connection", "close")
            self.end_headers()

        def _read_body(self) -> bytes:
            length = int(self.headers.get("Content-Length", 0))
            return self.rfile.read(length)

        def _read_form(self) -> dict:
            body = self._read_body().decode("utf-8")
            return dict(urllib.parse.parse_qsl(body))

        def _read_json(self) -> dict:
            body = self._read_body().decode("utf-8")
            return json.loads(body) if body else {}

        def _get_session_user(self) -> dict | None:
            cookie_header = self.headers.get("Cookie", "")
            cookies = http.cookies.SimpleCookie(cookie_header)
            token_morsel = cookies.get("session")
            if not token_morsel:
                return None
            user_id = store.get_session_user(token_morsel.value)
            if not user_id:
                return None
            return store.get_user(user_id)

        def _set_session_cookie(self, token: str):
            self.send_header(
                "Set-Cookie",
                f"session={token}; Path=/; HttpOnly; SameSite=Lax"
            )

        def _clear_session_cookie(self):
            self.send_header(
                "Set-Cookie",
                "session=; Path=/; HttpOnly; Max-Age=0"
            )

        # --- Routing ---

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            qs = dict(urllib.parse.parse_qsl(parsed.query))

            # Favicon — return empty 204 to prevent browser hang
            if path == "/favicon.ico":
                self.send_response(204)
                self.send_header("Connection", "close")
                self.end_headers()
                return

            # Health check for load balancers / deployment probes
            if path == "/healthz":
                self._send_json({"status": "ok", "timestamp": time.time()})
                return

            # Static files
            if path.startswith("/static/"):
                self._send_static(path[len("/static/"):])
                return

            user = self._get_session_user()

            # Pages
            if path == "/":
                self._send_html(_page_home(store, user, qs))
            elif path == "/post":
                if not user:
                    self._send_redirect("/join")
                else:
                    self._send_html(_page_post(user))
            elif path == "/join":
                self._send_html(_page_join())
            elif path == "/login":
                self._send_html(_page_login())
            elif path == "/logout":
                cookie_header = self.headers.get("Cookie", "")
                cookies = http.cookies.SimpleCookie(cookie_header)
                token_morsel = cookies.get("session")
                if token_morsel:
                    store.delete_session(token_morsel.value)
                self.send_response(303)
                self._clear_session_cookie()
                self.send_header("Location", "/")
                self.end_headers()
            elif path == "/settings":
                if not user:
                    self._send_redirect("/join")
                else:
                    self._send_html(_page_settings(store, user))
            elif path == "/invite":
                if not user:
                    self._send_redirect("/join")
                else:
                    self._send_html(_page_invite(store, user))
            elif path == "/status":
                self._send_html(_page_status(store, agent, user))
            elif re.match(r"^/job/[a-f0-9-]+$", path):
                job_id = path.split("/job/")[1]
                self._send_html(_page_job(store, job_id, user))
            # API endpoints
            elif path == "/api/jobs":
                jobs = store.list_jobs(
                    category=qs.get("category"),
                    status=qs.get("status"),
                )
                self._send_json({"jobs": jobs})
            elif path == "/api/stats":
                self._send_json(store.get_stats())
            elif re.match(r"^/api/jobs/[a-f0-9-]+$", path):
                job_id = path.split("/api/jobs/")[1]
                job = store.get_job(job_id)
                if job:
                    self._send_json(job)
                else:
                    self._send_json({"error": "Not found"}, 404)
            else:
                self._send_404()

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"

            user = self._get_session_user()

            if path == "/join":
                form = self._read_form()
                code = form.get("code", "").strip()
                handle = form.get("handle", "").strip()
                if not code or not handle:
                    self._send_html(_page_join("Invite code and handle are required."))
                    return
                ok, result = store.redeem_invite(code, handle)
                if not ok:
                    self._send_html(_page_join(result))
                    return
                # Create session
                token = store.create_session(result)
                self.send_response(303)
                self._set_session_cookie(token)
                self.send_header("Location", "/")
                self.end_headers()

            elif path == "/login":
                form = self._read_form()
                handle = form.get("handle", "").strip()
                if not handle:
                    self._send_html(_page_login("Handle is required."))
                    return
                u = store.get_user_by_handle(handle)
                if not u:
                    self._send_html(_page_login("No user with that handle."))
                    return
                token = store.create_session(u["id"])
                self.send_response(303)
                self._set_session_cookie(token)
                self.send_header("Location", "/")
                self.end_headers()

            elif path == "/post":
                if not user:
                    self._send_redirect("/join")
                    return
                form = self._read_form()
                title = form.get("title", "").strip()
                desc = form.get("description", "").strip()
                category = form.get("category", "factorization")

                # Parse params based on category
                params, err = _parse_post_params(category, form)
                if err:
                    self._send_html(_page_post(user, error=err))
                    return
                if not title:
                    self._send_html(_page_post(
                        user, error="Title is required."
                    ))
                    return

                job_id = store.create_job(
                    posted_by=user["id"],
                    title=title,
                    category=category,
                    description=desc,
                    params=params,
                )
                self._send_redirect(f"/job/{job_id}")

            elif re.match(r"^/job/[a-f0-9-]+/claim$", path):
                if not user:
                    self._send_redirect("/join")
                    return
                job_id = path.split("/job/")[1].split("/claim")[0]
                ok, msg = store.claim_job(job_id, user["id"])
                if ok:
                    job = store.get_job(job_id)
                    if job:
                        store.update_job_status(job_id, "running")
                        t = threading.Thread(
                            target=_run_job,
                            args=(store, agent, job_id,
                                  job["category"], job["params"]),
                            daemon=True,
                        )
                        t.start()
                self._send_redirect(f"/job/{job_id}")

            elif path == "/settings":
                if not user:
                    self._send_redirect("/join")
                    return
                form = self._read_form()
                config = {
                    "backend": form.get("backend", "local"),
                    "api_key": form.get("api_key", ""),
                    "model_name": form.get("model_name", ""),
                    "endpoint_url": form.get("endpoint_url", ""),
                }
                try:
                    config["max_threads"] = int(form.get("max_threads", 4))
                except ValueError:
                    config["max_threads"] = 4
                store.update_compute_config(user["id"], config)
                self._send_html(_page_settings(store, user, saved=True))

            elif path == "/invite":
                if not user:
                    self._send_redirect("/join")
                    return
                code = store.create_invite(created_by=user["id"])
                self._send_redirect("/invite")

            # JSON APIs
            elif path == "/api/jobs":
                if not user:
                    self._send_json({"error": "Unauthorized"}, 401)
                    return
                data = self._read_json()
                title = data.get("title", "")
                desc = data.get("description", "")
                params = data.get("params", {})
                category = data.get("category", "factorization")
                job_id = store.create_job(
                    posted_by=user["id"],
                    title=title,
                    category=category,
                    description=desc,
                    params=params,
                )
                self._send_json({"id": job_id}, 201)

            elif re.match(r"^/api/jobs/[a-f0-9-]+/claim$", path):
                if not user:
                    self._send_json({"error": "Unauthorized"}, 401)
                    return
                job_id = path.split("/api/jobs/")[1].split("/claim")[0]
                ok, msg = store.claim_job(job_id, user["id"])
                self._send_json({"ok": ok, "message": msg})

            else:
                self._send_json({"error": "Not found"}, 404)

    return Handler


def _parse_post_params(category: str, form: dict) -> tuple[dict, str]:
    """
    Parse and validate form params for a given category.

    Returns (params_dict, error_string). error_string is empty on success.
    """
    try:
        if category == "factorization":
            n = int(form.get("n", "").strip())
            if n < 4:
                return {}, "N must be an integer >= 4."
            return {"n": n}, ""

        elif category == "goldbach":
            n = int(form.get("goldbach_n", "").strip())
            if n < 4 or n % 2 != 0:
                return {}, "Must be an even integer >= 4."
            return {"n": n}, ""

        elif category == "collatz":
            start = int(form.get("collatz_start", "").strip())
            if start < 1:
                return {}, "Starting number must be >= 1."
            return {"start": start}, ""

        elif category == "perfect_numbers":
            lo = int(form.get("range_start", "").strip())
            hi = int(form.get("range_end", "").strip())
            if lo < 1 or hi <= lo:
                return {}, "Range end must be greater than range start (both >= 1)."
            return {"range_start": lo, "range_end": hi}, ""

        elif category == "primality":
            n = int(form.get("primality_n", "").strip())
            if n < 2:
                return {}, "N must be >= 2."
            return {"n": n}, ""

        else:
            n_str = form.get("other_n", "").strip()
            if n_str:
                n = int(n_str)
                return {"n": n}, ""
            return {}, ""

    except (ValueError, AttributeError):
        return {}, "Invalid numeric input."


def _run_job(store: Store, agent, job_id: str, category: str, params: dict):
    """Run a job based on its category. Dispatches to the right solver."""
    try:
        if category == "factorization":
            _run_factorization(store, agent, job_id, params["n"])
        elif category == "goldbach":
            _run_goldbach(store, job_id, params["n"])
        elif category == "collatz":
            _run_collatz(store, job_id, params["start"])
        elif category == "perfect_numbers":
            _run_perfect_numbers(store, job_id,
                                 params["range_start"], params["range_end"])
        elif category == "primality":
            _run_primality(store, job_id, params["n"])
        else:
            store.update_job_status(job_id, "failed", {
                "error": f"Unknown category: {category}"
            })
    except Exception as e:
        logger.exception("Job %s failed", job_id)
        store.update_job_status(job_id, "failed", {"error": str(e)})


def _run_factorization(store: Store, agent, job_id: str, n: int):
    """Run factorization via the agent network."""
    factors = agent.initiate_factorization(n, timeout=60.0)
    product = 1
    for f in factors:
        product *= f
    if product == n and factors:
        store.update_job_status(job_id, "solved", {
            "factors": factors,
            "product": product,
            "verification": "pass",
        })
    else:
        store.update_job_status(job_id, "solved", {
            "factors": factors,
            "product": product,
            "verification": "partial",
        })


def _run_goldbach(store: Store, job_id: str, n: int):
    """
    Goldbach conjecture: find two primes that sum to n.

    One of the oldest unsolved problems in mathematics (1742).
    Every even integer > 2 is conjectured to be the sum of two primes.
    Verified up to 4 x 10^18 but never proven.
    """
    from .._solver import goldbach_decomposition
    p, q = goldbach_decomposition(n)
    store.update_job_status(job_id, "solved", {
        "answer": f"{n} = {p} + {q}",
        "detail": f"Both {p} and {q} verified prime. "
                  f"Sum: {p} + {q} = {p + q}.",
    })


def _run_collatz(store: Store, job_id: str, start: int):
    """
    Collatz conjecture (3n+1 problem): does the sequence always reach 1?

    Unsolved since 1937. Verified for all starting values up to ~10^20.
    """
    from .._solver import collatz_sequence
    length, max_val, reached_one = collatz_sequence(start)
    status = "solved" if reached_one else "failed"
    store.update_job_status(job_id, status, {
        "answer": f"Sequence from {start}: length={length}, max={max_val}, reached_1={reached_one}",
        "detail": f"Starting at {start}, the sequence took {length} steps "
                  f"and reached a maximum value of {max_val}.",
    })


def _run_perfect_numbers(store: Store, job_id: str, lo: int, hi: int):
    """
    Search for perfect numbers in [lo, hi].

    Only 51 perfect numbers are known as of 2024. All known ones are even.
    Whether odd perfect numbers exist is one of the oldest open questions
    in mathematics (over 2000 years).
    """
    from .._solver import find_perfect_numbers
    found = find_perfect_numbers(lo, hi)
    if found:
        answer = f"Found {len(found)} perfect number(s): {', '.join(map(str, found))}"
    else:
        answer = f"No perfect numbers found in [{lo}, {hi}]"
    store.update_job_status(job_id, "solved", {
        "answer": answer,
        "detail": f"Searched range [{lo}, {hi}]. "
                  f"A perfect number equals the sum of its proper divisors.",
    })


def _run_primality(store: Store, job_id: str, n: int):
    """
    Distributed primality testing using Miller-Rabin with many witnesses.

    For very large numbers, distributed witnesses increase confidence.
    """
    from .._solver import primality_test
    is_prime, witnesses = primality_test(n)
    verdict = "PRIME" if is_prime else "COMPOSITE"
    store.update_job_status(job_id, "solved", {
        "answer": f"{n} is {verdict}",
        "detail": f"Tested with {witnesses} Miller-Rabin witnesses.",
    })


# ---------------------------------------------------------------------------
# HTML page renderers (Craigslist-inspired, minimal, text-heavy)
# ---------------------------------------------------------------------------

_CSS_LINK = '<link rel="stylesheet" href="/static/style.css">'


def _nav(user: dict | None) -> str:
    links = [
        '<a href="/">gradatim</a>',
        '<a href="/status">status</a>',
    ]
    if user:
        links.append(f'<a href="/post">post problem</a>')
        links.append(f'<a href="/invite">invites</a>')
        links.append(f'<a href="/settings">settings</a>')
        links.append(
            f'<span class="nav-user">[{_esc(user["handle"])}]</span>'
            f' <a href="/logout">logout</a>'
        )
    else:
        links.append('<a href="/join">join</a>')
        links.append('<a href="/login">login</a>')
    return '<nav class="topnav">' + " | ".join(links) + "</nav>"


def _esc(s) -> str:
    """Minimal HTML escaping."""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _render_params(category: str, params: dict) -> str:
    """Render the params section for a job detail page."""
    if category == "factorization":
        return f'<p><b>N =</b> <code>{params.get("n", "?")}</code></p>'
    elif category == "goldbach":
        return (f'<p><b>Even number =</b> <code>{params.get("n", "?")}</code></p>'
                f'<p class="param-hint">Find two primes that sum to this even number.</p>')
    elif category == "collatz":
        return (f'<p><b>Starting value =</b> <code>{params.get("start", "?")}</code></p>'
                f'<p class="param-hint">Compute the Collatz sequence and verify it reaches 1.</p>')
    elif category == "perfect_numbers":
        lo = params.get("range_start", "?")
        hi = params.get("range_end", "?")
        return (f'<p><b>Search range =</b> <code>[{lo}, {hi}]</code></p>'
                f'<p class="param-hint">Find all perfect numbers in this range '
                f'(numbers equal to the sum of their proper divisors).</p>')
    elif category == "primality":
        return (f'<p><b>N =</b> <code>{params.get("n", "?")}</code></p>'
                f'<p class="param-hint">Determine if this number is prime.</p>')
    else:
        lines = "".join(f"<li><b>{_esc(k)}:</b> <code>{_esc(v)}</code></li>"
                        for k, v in params.items())
        return f"<ul>{lines}</ul>"


def _param_summary(job: dict) -> str:
    """Generate a short parameter summary for job listings."""
    cat = job.get("category", "")
    p = job.get("params", {})
    if cat == "factorization":
        return f"n={p.get('n', '?')}"
    elif cat == "goldbach":
        return f"n={p.get('n', '?')}"
    elif cat == "collatz":
        return f"start={p.get('start', '?')}"
    elif cat == "perfect_numbers":
        lo = p.get("range_start", "?")
        hi = p.get("range_end", "?")
        return f"range=[{lo},{hi}]"
    elif cat == "primality":
        return f"n={p.get('n', '?')}"
    else:
        return ", ".join(f"{k}={v}" for k, v in p.items())[:60]


def _layout(title: str, body: str, user: dict | None = None) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)} - gradatim</title>
{_CSS_LINK}
</head>
<body>
<div class="container">
<header>
<h1 class="site-title"><a href="/">gradatim</a></h1>
<p class="tagline">collaborative compute network &middot; step by step</p>
{_nav(user)}
</header>
<hr>
{body}
<hr>
<footer>
<p class="footer-text">gradatim v0.1 &middot; decentralized agent network &middot;
zero external dependencies &middot; own the stack</p>
</footer>
</div>
</body>
</html>"""


def _page_home(store: Store, user: dict | None, qs: dict) -> str:
    category = qs.get("category")
    status_filter = qs.get("status")
    jobs = store.list_jobs(category=category, status=status_filter)
    stats = store.get_stats()

    # Category links
    cats = f"""
    <div class="categories">
      <b>categories:</b>
      <a href="/">all</a> |
      <a href="/?category=factorization">factorization</a> |
      <a href="/?category=goldbach">goldbach</a> |
      <a href="/?category=collatz">collatz</a> |
      <a href="/?category=perfect_numbers">perfect numbers</a> |
      <a href="/?category=primality">primality</a> |
      <a href="/?category=other">other</a>
      &nbsp;&nbsp;&nbsp;
      <b>filter:</b>
      <a href="/">all</a> |
      <a href="/?status=open">open</a> |
      <a href="/?status=running">running</a> |
      <a href="/?status=solved">solved</a>
    </div>
    """

    # Stats bar
    stats_bar = f"""
    <div class="stats-bar">
      {stats['open_jobs']} open &middot;
      {stats['running_jobs']} running &middot;
      {stats['solved_jobs']} solved &middot;
      {stats['total_users']} users
    </div>
    """

    # Job listings
    if not jobs:
        listing = '<p class="empty">No problems posted yet. <a href="/post">Post one.</a></p>'
    else:
        rows = []
        for j in jobs:
            status_class = j["status"]
            date = _format_time(j["posted_at"])
            param_summary = _param_summary(j)
            poster = store.get_user(j["posted_by"])
            poster_name = poster["handle"] if poster else "unknown"
            workers = len(j.get("workers", []))
            rows.append(f"""
            <tr class="job-row {status_class}">
              <td class="job-date">{date}</td>
              <td class="job-status"><span class="badge badge-{status_class}">{j['status']}</span></td>
              <td class="job-title">
                <a href="/job/{j['id']}">{_esc(j['title'])}</a>
                <span class="job-meta">{param_summary}</span>
              </td>
              <td class="job-cat">{_esc(j['category'])}</td>
              <td class="job-poster">{_esc(poster_name)}</td>
              <td class="job-workers">{workers} worker{'s' if workers != 1 else ''}</td>
            </tr>
            """)

        listing = f"""
        <table class="jobs-table">
          <thead>
            <tr>
              <th>date</th>
              <th>status</th>
              <th>problem</th>
              <th>category</th>
              <th>posted by</th>
              <th>workers</th>
            </tr>
          </thead>
          <tbody>
            {"".join(rows)}
          </tbody>
        </table>
        """

    body = f"""
    <div class="board-header">
      <h2>problem board</h2>
      {cats}
      {stats_bar}
    </div>
    {listing}
    """
    return _layout("problems", body, user)


def _page_job(store: Store, job_id: str, user: dict | None) -> str:
    job = store.get_job(job_id)
    if not job:
        return _layout("not found", "<h2>Job not found</h2>", user)

    poster = store.get_user(job["posted_by"])
    poster_name = poster["handle"] if poster else "unknown"
    date = _format_time(job["posted_at"])
    params = job.get("params", {})

    result_html = ""
    if job["result"]:
        r = job["result"]
        if "error" in r:
            result_html = f"""
            <div class="result-box result-error">
              <h3>error</h3>
              <p>{_esc(r['error'])}</p>
            </div>
            """
        elif "factors" in r:
            factors_str = " &times; ".join(str(f) for f in r["factors"])
            n_val = params.get("n", "?")
            result_html = f"""
            <div class="result-box">
              <h3>result</h3>
              <p class="result-factors">{n_val} = {factors_str}</p>
              <p>Product check: {r.get('product', '?')} &mdash;
                 verification: <b>{r.get('verification', '?')}</b></p>
            </div>
            """
        elif "answer" in r:
            result_html = f"""
            <div class="result-box">
              <h3>result</h3>
              <p class="result-factors">{_esc(r['answer'])}</p>
              {'<p>' + _esc(r.get('detail', '')) + '</p>' if r.get('detail') else ''}
            </div>
            """

    claim_btn = ""
    if job["status"] == "open" and user:
        claim_btn = f"""
        <form method="POST" action="/job/{job_id}/claim" class="claim-form">
          <button type="submit" class="btn">claim &amp; solve this problem</button>
        </form>
        """
    elif job["status"] == "open" and not user:
        claim_btn = '<p><a href="/join">Join</a> to claim this problem.</p>'
    elif job["status"] == "running":
        claim_btn = '<p class="running-msg">solving in progress...</p>'

    workers_html = ""
    if job["workers"]:
        names = []
        for wid in job["workers"]:
            wu = store.get_user(wid)
            names.append(wu["handle"] if wu else "unknown")
        workers_html = f'<p><b>workers:</b> {", ".join(_esc(n) for n in names)}</p>'

    body = f"""
    <div class="job-detail">
      <h2>{_esc(job['title'])}</h2>
      <div class="job-detail-meta">
        <span class="badge badge-{job['status']}">{job['status']}</span>
        &middot; posted by <b>{_esc(poster_name)}</b>
        &middot; {date}
        &middot; category: {_esc(job['category'])}
      </div>
      <div class="job-detail-params">
        {_render_params(job['category'], params)}
      </div>
      <div class="job-detail-desc">
        <p>{_esc(job['description'])}</p>
      </div>
      {workers_html}
      {claim_btn}
      {result_html}
    </div>
    <p><a href="/">&laquo; back to board</a></p>
    """
    return _layout(job["title"], body, user)


def _page_post(user: dict, error: str = "") -> str:
    err_html = f'<p class="form-error">{_esc(error)}</p>' if error else ""
    body = f"""
    <h2>post a problem</h2>
    {err_html}
    <form method="POST" action="/post" class="post-form">
      <label for="title">title</label>
      <input type="text" name="title" id="title" placeholder="e.g. Factor 5959"
             required maxlength="200">

      <label for="category">category</label>
      <select name="category" id="category" onchange="toggleCategoryFields()">
        <option value="factorization" selected>factorization</option>
        <option value="goldbach">goldbach conjecture</option>
        <option value="collatz">collatz conjecture</option>
        <option value="perfect_numbers">perfect number search</option>
        <option value="primality">primality testing</option>
        <option value="other">other</option>
      </select>

      <div id="fields-factorization" class="category-fields">
        <label for="n">number to factor (N)</label>
        <input type="text" name="n" id="n" placeholder="e.g. 5959">
      </div>

      <div id="fields-goldbach" class="category-fields" style="display:none">
        <label for="goldbach_n">even number to decompose</label>
        <input type="text" name="goldbach_n" id="goldbach_n"
               placeholder="e.g. 100 (must be even, >= 4)">
        <p class="param-hint">Find two primes p + q = n. Every even integer &gt; 2
           is conjectured to be the sum of two primes.</p>
      </div>

      <div id="fields-collatz" class="category-fields" style="display:none">
        <label for="collatz_start">starting number</label>
        <input type="text" name="collatz_start" id="collatz_start"
               placeholder="e.g. 27">
        <p class="param-hint">Compute the Collatz sequence (3n+1 problem).
           Verify it reaches 1 and report the sequence length and max value.</p>
      </div>

      <div id="fields-perfect_numbers" class="category-fields" style="display:none">
        <label for="range_start">range start</label>
        <input type="text" name="range_start" id="range_start" placeholder="e.g. 1">
        <label for="range_end">range end</label>
        <input type="text" name="range_end" id="range_end" placeholder="e.g. 10000">
        <p class="param-hint">Search for perfect numbers (n = sum of its proper divisors).
           Only 51 are known. Can you find the ones in your range?</p>
      </div>

      <div id="fields-primality" class="category-fields" style="display:none">
        <label for="primality_n">number to test</label>
        <input type="text" name="primality_n" id="primality_n"
               placeholder="e.g. 170141183460469231731687303715884105727">
        <p class="param-hint">Determine if this number is prime using distributed
           Miller-Rabin testing with multiple witnesses.</p>
      </div>

      <div id="fields-other" class="category-fields" style="display:none">
        <label for="other_n">input number (N)</label>
        <input type="text" name="other_n" id="other_n" placeholder="numeric input">
      </div>

      <label for="description">description (optional)</label>
      <textarea name="description" id="description" rows="4"
                placeholder="Any details about the problem..."></textarea>

      <button type="submit" class="btn">post problem</button>
    </form>
    <script>
    function toggleCategoryFields() {{
      var cat = document.getElementById('category').value;
      var all = document.querySelectorAll('.category-fields');
      for (var i = 0; i < all.length; i++) all[i].style.display = 'none';
      var el = document.getElementById('fields-' + cat);
      if (el) el.style.display = 'block';
    }}
    </script>
    <p><a href="/">&laquo; back to board</a></p>
    """
    return _layout("post a problem", body, user)


def _page_join(error: str = "") -> str:
    err_html = f'<p class="form-error">{_esc(error)}</p>' if error else ""
    body = f"""
    <h2>join gradatim</h2>
    <p>You need an invite code to join. Get one from an existing member.</p>
    {err_html}
    <form method="POST" action="/join" class="join-form">
      <label for="code">invite code</label>
      <input type="text" name="code" id="code" required placeholder="paste your invite code">

      <label for="handle">choose a handle</label>
      <input type="text" name="handle" id="handle" required
             placeholder="your username" maxlength="30">

      <button type="submit" class="btn">join</button>
    </form>
    <p>Already have an account? <a href="/login">Log in.</a></p>
    <p><a href="/">&laquo; back to board</a></p>
    """
    return _layout("join", body)


def _page_login(error: str = "") -> str:
    err_html = f'<p class="form-error">{_esc(error)}</p>' if error else ""
    body = f"""
    <h2>log in</h2>
    {err_html}
    <form method="POST" action="/login" class="login-form">
      <label for="handle">handle</label>
      <input type="text" name="handle" id="handle" required placeholder="your username">

      <button type="submit" class="btn">log in</button>
    </form>
    <p>Need an account? <a href="/join">Join with an invite code.</a></p>
    <p><a href="/">&laquo; back to board</a></p>
    """
    return _layout("log in", body)


def _page_settings(store: Store, user: dict, saved: bool = False) -> str:
    config = store.get_compute_config(user["id"]) or {}
    saved_html = '<p class="form-success">Settings saved.</p>' if saved else ""

    def _sel(field, val):
        return "selected" if config.get("backend") == val else ""

    body = f"""
    <h2>compute settings</h2>
    <p>Configure how you contribute compute to the network.</p>
    {saved_html}
    <form method="POST" action="/settings" class="settings-form">
      <fieldset>
        <legend>compute backend</legend>

        <label for="backend">backend type</label>
        <select name="backend" id="backend" onchange="toggleBackendFields()">
          <option value="local" {_sel('backend','local')}>Local (built-in Python)</option>
          <option value="openai" {_sel('backend','openai')}>OpenAI API</option>
          <option value="anthropic" {_sel('backend','anthropic')}>Anthropic API</option>
          <option value="ollama" {_sel('backend','ollama')}>Ollama (local model)</option>
          <option value="custom" {_sel('backend','custom')}>Custom endpoint</option>
        </select>

        <div id="api-fields" class="backend-fields">
          <label for="api_key">API key</label>
          <input type="password" name="api_key" id="api_key"
                 value="{_esc(config.get('api_key', ''))}"
                 placeholder="sk-...">

          <label for="model_name">model name</label>
          <input type="text" name="model_name" id="model_name"
                 value="{_esc(config.get('model_name', ''))}"
                 placeholder="e.g. gpt-4, claude-sonnet-4-5-20250929, llama3">
        </div>

        <div id="endpoint-fields" class="backend-fields">
          <label for="endpoint_url">endpoint URL</label>
          <input type="text" name="endpoint_url" id="endpoint_url"
                 value="{_esc(config.get('endpoint_url', ''))}"
                 placeholder="http://localhost:11434/api/generate">
        </div>

        <label for="max_threads">max worker threads</label>
        <input type="number" name="max_threads" id="max_threads"
               value="{config.get('max_threads', 4)}" min="1" max="32">
      </fieldset>

      <button type="submit" class="btn">save settings</button>
    </form>
    <script>
    function toggleBackendFields() {{
      var b = document.getElementById('backend').value;
      var api = document.getElementById('api-fields');
      var ep = document.getElementById('endpoint-fields');
      api.style.display = (b === 'openai' || b === 'anthropic' || b === 'custom') ? 'block' : 'none';
      ep.style.display = (b === 'ollama' || b === 'custom') ? 'block' : 'none';
    }}
    toggleBackendFields();
    </script>
    <p><a href="/">&laquo; back to board</a></p>
    """
    return _layout("settings", body, user)


def _page_invite(store: Store, user: dict) -> str:
    invites = store.list_invites(created_by=user["id"])

    # Also show system invites if user is system
    if user.get("is_system"):
        invites = store.list_invites()

    rows = []
    for inv in invites:
        status = "used" if inv["redeemed_by"] else "available"
        redeemed_html = ""
        if inv["redeemed_by"]:
            ru = store.get_user(inv["redeemed_by"])
            rname = ru["handle"] if ru else "unknown"
            redeemed_html = f" by <b>{_esc(rname)}</b>"

        rows.append(f"""
        <tr>
          <td><code class="invite-code">{_esc(inv['code'])}</code></td>
          <td>{_format_time(inv['created_at'])}</td>
          <td><span class="badge badge-{'solved' if status == 'used' else 'open'}">{status}</span>{redeemed_html}</td>
        </tr>
        """)

    table = f"""
    <table class="invites-table">
      <thead><tr><th>code</th><th>created</th><th>status</th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
    """ if rows else "<p>No invites yet.</p>"

    body = f"""
    <h2>invite codes</h2>
    <p>Share these codes with people you want to invite to the network.</p>
    <form method="POST" action="/invite" class="invite-gen-form">
      <button type="submit" class="btn">generate new invite code</button>
    </form>
    <h3>your invites</h3>
    {table}
    <p><a href="/">&laquo; back to board</a></p>
    """
    return _layout("invites", body, user)


def _page_status(store: Store, agent, user: dict | None) -> str:
    stats = store.get_stats()

    agent_info = ""
    if agent:
        peers = agent.get_peers()
        peer_rows = []
        for p in peers:
            peer_rows.append(f"""
            <tr>
              <td><code>{p.peer_id.hex()[:12]}...</code></td>
              <td>{p.host}:{p.port}</td>
              <td>{', '.join(p.capabilities) if p.capabilities else '-'}</td>
              <td>{_format_time(p.last_seen)}</td>
            </tr>
            """)
        peers_table = f"""
        <table class="peers-table">
          <thead><tr><th>peer ID</th><th>address</th><th>capabilities</th><th>last seen</th></tr></thead>
          <tbody>{"".join(peer_rows)}</tbody>
        </table>
        """ if peer_rows else "<p>No peers connected.</p>"

        agent_info = f"""
        <h3>local agent</h3>
        <ul>
          <li><b>agent ID:</b> <code>{agent.agent_id}</code></li>
          <li><b>listening on:</b> {agent.host}:{agent.port}</li>
          <li><b>peers:</b> {agent.get_peer_count()}</li>
          <li><b>capabilities:</b> {', '.join(agent.capabilities)}</li>
        </ul>
        <h3>connected peers</h3>
        {peers_table}
        """
    else:
        agent_info = "<p>No agent running. Start the server with an agent to see network status.</p>"

    body = f"""
    <h2>network status</h2>
    <div class="status-grid">
      <div class="stat-card">
        <div class="stat-number">{stats['total_jobs']}</div>
        <div class="stat-label">total problems</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">{stats['open_jobs']}</div>
        <div class="stat-label">open</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">{stats['solved_jobs']}</div>
        <div class="stat-label">solved</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">{stats['total_users']}</div>
        <div class="stat-label">users</div>
      </div>
    </div>
    {agent_info}
    <p><a href="/">&laquo; back to board</a></p>
    """
    return _layout("status", body, user)


def _page_404() -> str:
    return _layout("not found", """
    <h2>404 - not found</h2>
    <p>Nothing here. <a href="/">Go back to the board.</a></p>
    """)


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

def run_server(host: str = "127.0.0.1", port: int = 8080,
               agent=None):
    """
    Start the Gradatim web server.

    Args:
        host: Bind address.
        port: Bind port.
        agent: An optional Agent instance for live factorization.
    """
    store = Store()
    handler_class = _make_handler(store, agent)
    server = ThreadingHTTPServer((host, port), handler_class)
    print(f"Gradatim web server running at http://{host}:{port}")
    print(f"  Invite codes (for first-time join):")
    for inv in store.list_invites():
        if not inv["redeemed_by"]:
            print(f"    {inv['code']}")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()
