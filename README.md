# LLM Analysis Quiz – Automated Solver

Backend for IITM TDS Sep 2025 Project 2.

## Features
- Validates secret
- Renders JS using Playwright
- Downloads PDF/CSV
- Extracts "value" from tables
- Submits answer to submit URL
- Works under 3-minute limit

## Run locally
```
pip install -r requirements.txt
playwright install
export QUIZ_SECRET="your_secret"
python app.py
```

## Test with demo
```
curl -X POST http://localhost:5000/api/solve  -H "Content-Type: application/json"  -d '{"email":"your_email", "secret":"your_secret", "url":"https://tds-llm-analysis.s-anand.net/demo"}'
```

## Deployment
Works on:
- Railway
- Render
- VPS
