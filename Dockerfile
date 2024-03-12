FROM ghcr.io/void-linux/void-glibc

RUN xbps-install -Syu
RUN xbps-install -y python3 python3-lxml python3-Flask python3-urllib3 python3-pycountry python3-hypercorn python3-httpx calibre

WORKDIR /app
COPY . .

EXPOSE 5000
CMD ["hypercorn", "main:app", "--bind", "0.0.0.0:5000"]
