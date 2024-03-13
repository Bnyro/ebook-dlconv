FROM python:3.12
WORKDIR /app

RUN apt update && apt install -y calibre

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY ./ .

EXPOSE 5000
CMD ["gunicorn", "main:app", "--bind", "0.0.0.0:5000"]
