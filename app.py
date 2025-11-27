from flask import Flask, request, jsonify
import asyncio, time, os, json, tempfile, base64, requests, signal
from playwright.async_api import async_playwright
import PyPDF2
import io
import pandas as pd
import re

app = Flask(__name__)

SECRET_EXPECTED = os.environ.get("QUIZ_SECRET", "changeme")
MAX_PROCESS_SECONDS = 170  # must stay under 180 seconds


# ----------------------------------------------------------------------
# TIMEOUT HANDLER
# ----------------------------------------------------------------------
def timeout_handler(signum, frame):
    raise TimeoutError("Processing time exceeded")


# ----------------------------------------------------------------------
# PDF VALUE SUM
# ----------------------------------------------------------------------
def sum_value_from_pdf_bytes(pdf_bytes):
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        lines = text.splitlines()

        total = 0
        found = False
        for ln in lines:
            parts = ln.replace(",", " ").split()
            for i, tok in enumerate(parts):
                if tok.lower() == "value" and i + 1 < len(parts):
                    try:
                        total += float(parts[i + 1])
                        found = True
                    except:
                        pass
        return total if found else None
    except:
        return None


# ----------------------------------------------------------------------
# CSV VALUE SUM
# ----------------------------------------------------------------------
def sum_value_from_csv(path):
    try:
        df = pd.read_csv(path)
    except:
        return None

    for col in df.columns:
        if col.lower() == "value":
            return float(df[col].sum())

    numeric = df.select_dtypes(include=["number"])
    if not numeric.empty:
        return float(numeric.iloc[:, 0].sum())

    return None


# ----------------------------------------------------------------------
# DOWNLOAD ALL FILES ON PAGE
# ----------------------------------------------------------------------
async def download_all_files(page, save_dir):
    anchors = await page.eval_on_selector_all(
        "a", "els => els.map(e => ({href: e.href, text: e.innerText}))"
    )

    files = []
    for a in anchors:
        href = a.get("href")
        if not href:
            continue

        # Base64 embedded files
        if href.startswith("data:") and "base64" in href:
            header, b64 = href.split(",", 1)
            data = base64.b64decode(b64)

            ext = ".pdf" if "pdf" in header else ".bin"
            filename = os.path.join(save_dir, f"embedded{len(files)}{ext}")

            with open(filename, "wb") as f:
                f.write(data)
            files.append(filename)

        # Normal downloadable URLs
        elif href.startswith("http"):
            try:
                r = requests.get(href, timeout=20)
                if r.status_code == 200:
                    name = href.split("/")[-1] or f"file{len(files)}.bin"
                    filename = os.path.join(save_dir, name)

                    with open(filename, "wb") as f:
                        f.write(r.content)

                    files.append(filename)
            except:
                pass

    return files


# ----------------------------------------------------------------------
# SOLVE QUIZ
# ----------------------------------------------------------------------
async def solve_quiz(page, body_text, html, url, save_dir):

    # ---------------------------------------------------------------
    # 1. Decode base64 HTML inside atob(`...`)
    # ---------------------------------------------------------------
    b64_blocks = re.findall(r'atob\(`([A-Za-z0-9+/=\n]+)`\)', body_text + html)

    for block in b64_blocks:
        try:
            decoded = base64.b64decode(block).decode("utf-8", errors="ignore")
            body_text += "\n" + decoded
            html += "\n" + decoded
        except:
            pass

    # ---------------------------------------------------------------
    # 2. Try downloaded files
    # ---------------------------------------------------------------
    downloaded = await download_all_files(page, save_dir)

    for f in downloaded:
        if f.endswith(".pdf"):
            with open(f, "rb") as pdf_file:
                val = sum_value_from_pdf_bytes(pdf_file.read())
                if val is not None:
                    return val

        if f.endswith(".csv"):
            val = sum_value_from_csv(f)
            if val is not None:
                return val

    # ---------------------------------------------------------------
    # 3. Try HTML tables directly
    # ---------------------------------------------------------------
    try:
        tables = await page.query_selector_all("table")
        for t in tables:
            try:
                html_table = await t.inner_html()
                df_list = pd.read_html(html_table)
                if df_list:
                    df = df_list[0]

                    for col in df.columns:
                        if "value" in str(col).lower():
                            return float(df[col].sum())
            except:
                pass
    except:
        pass

    # ---------------------------------------------------------------
    # Fallback: no answer found
    # ---------------------------------------------------------------
    return None


# ----------------------------------------------------------------------
# MAIN API ENDPOINT
# ----------------------------------------------------------------------
@app.route("/api/solve", methods=["POST"])
def api_solve():
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(MAX_PROCESS_SECONDS)

    try:
        payload = request.get_json(force=True)
    except:
        return jsonify({"error": "invalid json"}), 400

    email = payload.get("email")
    secret = payload.get("secret")
    url = payload.get("url")

    if secret != SECRET_EXPECTED:
        return jsonify({"error": "invalid secret"}), 403

    if not url or not email:
        return jsonify({"error": "missing fields"}), 400

    result = asyncio.run(handle(url, email, secret))
    signal.alarm(0)

    return jsonify(result), 200


# ----------------------------------------------------------------------
# HANDLE FULL QUIZ PROCESS
# ----------------------------------------------------------------------
async def handle(url, email, secret):
    tempdir = tempfile.mkdtemp()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox"])
        ctx = await browser.new_context()
        page = await ctx.new_page()

        await page.goto(url, wait_until="networkidle", timeout=90000)

        body_text = await page.inner_text("body")
        html = await page.content()

        # -----------------------------------------------------------
        # Solve quiz
        # -----------------------------------------------------------
        answer = await solve_quiz(page, body_text, html, url, tempdir)

        # -----------------------------------------------------------
        # Find submit URL (robust)
        # -----------------------------------------------------------
        combined = body_text + "\n" + html
        submit_urls = re.findall(
            r'https?://[^\s"\'<>]+/submit[^\s"\'<>]*',
            combined,
        )

        submit_url = submit_urls[0] if submit_urls else None

        if not submit_url:
            return {"error": "Submit URL not found"}

        # -----------------------------------------------------------
        # Build submission payload
        # -----------------------------------------------------------
        submit_payload = {
            "email": email,
            "secret": secret,
            "url": url,
            "answer": answer,
        }

        # -----------------------------------------------------------
        # Send final answer
        # -----------------------------------------------------------
        resp = requests.post(submit_url, json=submit_payload, timeout=30)

        try:
            return resp.json()
        except:
            return {"status": resp.status_code, "text": resp.text}


# ----------------------------------------------------------------------
# END
# ----------------------------------------------------------------------
