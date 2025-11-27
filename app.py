from flask import Flask, request, jsonify
import asyncio, time, os, json, tempfile, base64, requests, signal
from urllib.parse import urljoin
from playwright.async_api import async_playwright
import PyPDF2
import io
import pandas as pd

app = Flask(__name__)

SECRET_EXPECTED = os.environ.get("QUIZ_SECRET", "changeme")
MAX_PROCESS_SECONDS = 170

def timeout_handler(signum, frame):
    raise TimeoutError("Processing time exceeded")

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
                if tok.lower() == "value" and i+1 < len(parts):
                    try:
                        total += float(parts[i+1])
                        found = True
                    except:
                        pass
        return total if found else None
    except:
        return None

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
        return float(numeric.iloc[:,0].sum())
    return None

async def download_all_files(page, save_dir):
    anchors = await page.eval_on_selector_all(
        "a", "els => els.map(e => ({href: e.href, text: e.innerText}))"
    )
    files = []
    for a in anchors:
        href = a.get("href")
        if not href:
            continue
        if href.startswith("data:") and "base64" in href:
            header, b64 = href.split(",", 1)
            data = base64.b64decode(b64)
            ext = ".pdf" if "pdf" in header else ".bin"
            filename = os.path.join(save_dir, f"embedded{len(files)}{ext}")
            with open(filename, "wb") as f:
                f.write(data)
            files.append(filename)
        elif href.startswith("http"):
            try:
                r = requests.get(href, timeout=20)
                if r.status_code == 200:
                    filename = os.path.join(save_dir, href.split("/")[-1] or f"file{len(files)}.bin")
                    with open(filename, "wb") as f:
                        f.write(r.content)
                    files.append(filename)
            except:
                pass
    return files

async def solve_quiz(page, body_text, base_url, save_dir):
    import re
    matches = re.findall(r'atob\(`([A-Za-z0-9+/=\\n]+)`\)', body_text)
    for m in matches:
        try:
            decoded = base64.b64decode(m)
            pdf_val = sum_value_from_pdf_bytes(decoded)
            if pdf_val is not None:
                return pdf_val
        except:
            pass
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
    try:
        tables = await page.query_selector_all("table")
        for t in tables:
            html = await t.inner_html()
            df_list = pd.read_html(html)
            if df_list:
                df = df_list[0]
                for col in df.columns:
                    if "value" in str(col).lower():
                        return float(df[col].sum())
    except:
        pass
    return None

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
    if not url:
        return jsonify({"error": "missing url"}), 400

    result = asyncio.run(handle(url, email, secret))
    signal.alarm(0)
    return jsonify(result), 200

async def handle(url, email, secret):
    tempdir = tempfile.mkdtemp()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox"])
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(url, wait_until="networkidle", timeout=90000)
        body_text = await page.inner_text("body")
        html = await page.content()
        answer = await solve_quiz(page, body_text, url, tempdir)
        import re
        submit_urls = re.findall(r'https?://[^\s"\'<>]+/submit[^\s"\'<>]*', body_text + html)
        submit_url = submit_urls[0] if submit_urls else None

        if not submit_url:
            return {"error": "Submit URL not found"}

        resp = requests.post(submit_url, json={
            "email": email,
            "secret": secret,
            "url": url,
            "answer": answer
        }, timeout=30)

        try:
            return resp.json()
        except:
            return {"status": resp.status_code, "text": resp.text}
