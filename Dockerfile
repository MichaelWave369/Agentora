FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt server/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 8088 8501

CMD ["bash", "-lc", "uvicorn app.main:app --app-dir server --host 0.0.0.0 --port 8088 & streamlit run app.py --server.address=0.0.0.0 --server.port=8501"]
