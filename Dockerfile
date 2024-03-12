FROM debian

RUN apt update && apt upgrade
RUN apt install -y python3 python3-lxml python3-flask python3-urllib3 python3-pycountry python3-hypercorn python3-httpx calibre

WORKDIR /app
COPY . .

EXPOSE 5000
CMD ["hypercorn", "main:app", "--bind", "0.0.0.0:5000"]