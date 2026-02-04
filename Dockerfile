FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py db.py models.py google_sheets.py habitbot_template_EN.xlsx /app/
COPY web /app/web
COPY onboarding /app/onboarding

CMD ["python", "bot.py"]
