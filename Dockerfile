FROM --platform=linux/amd64 python:3.9-slim

WORKDIR /app

COPY process_pdfs.py .

RUN pip install --no-cache-dir PyMuPDF langdetect

CMD ["python", "process_pdfs.py"]
