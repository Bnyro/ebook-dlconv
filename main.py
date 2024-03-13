from flask import Flask, render_template, Response, request, send_from_directory, redirect
from urllib.parse import urlencode, quote_plus
from lxml import html
from lxml.etree import ElementBase, _ElementStringResult, _ElementUnicodeResult
from numbers import Number
from datetime import datetime, timedelta
import time
import httpx
import pycountry
import shutil
import os
import subprocess
import re
import threading

HOUR_DELAY = 1
TEMP_DIR = "./temp"
OUTPUT_DIR = "./output"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0"

base_url = "https://annas-archive.org"

languages = [{'name': country.name, 'code': country.alpha_2.lower()} for country in pycountry.countries]
languages.sort(key=lambda lang: lang['name'])
headers = {'User-Agent': USER_AGENT}

app = Flask(__name__)


for dir in (TEMP_DIR, OUTPUT_DIR):
    if not os.path.exists(dir):
        os.mkdir(dir)


@app.route('/')
def index():
    files = os.listdir(OUTPUT_DIR)

    return render_template('index.html', languages=languages, files=files)


@app.route('/dl/<path:name>')
def dl(name):
    return send_from_directory(OUTPUT_DIR, name, as_attachment=True)


@app.route('/delete/<path:name>')
def delete(name):
    path = os.path.join(OUTPUT_DIR, name)
    if os.path.exists(path):
        os.remove(path)

    return redirect("/")


@app.route('/search', methods=["GET", "POST"])
def search():
    query = get_param(request, "q")
    lang = get_param(request, "lang")

    if query is None:
        return render_template('search.html', default_lang=lang, languages=languages)

    args = {'q': query}

    if lang is not None and lang:
        args['lang'] = lang

    url = f"{base_url}/search?{urlencode(args)}"
    response = httpx.get(url, headers=headers)
    if response.status_code != 200:
        return "Invalid response from Anna's Archive", 500

    results = extract_search_results(response.text)

    return render_template('search.html', query=query, default_lang=lang, results=results, languages=languages)


@app.route('/download')
def download():
    id = get_param(request, "id")
    title = get_param(request, "title")
    extension = get_param(request, "ext")

    if id is None:
        return "Query missing", 400

    return Response(start_download(id, title, extension), mimetype="text/html")


def start_download(id, title, extension):
    yield f"<title>Downloading {title}</title>"

    yield "Extracting links... <br />"
    download_link = extract_download_link(id)
    if download_link is None:
        yield "No links found, aborting! <br />"
        yield "<a href='/'>Go Home</a>"
        return

    yield "Links found... <br />"

    dl_thread = threading.Thread(
        target=download_file,
        args=(
            download_link,
            title,
            extension,
        ),
    )
    dl_thread.start()

    yield "Started download on background... <br />"
    yield "<a href='/'>Go Home</a>"


def download_file(download_link, title, extension):
    r = httpx.get(download_link, timeout=100, follow_redirects=True, headers=headers)
    temp_file = os.path.join(TEMP_DIR, f"{title}.{extension}")
    with open(temp_file, 'wb') as f:
        f.write(r.content)

    out_file = os.path.join(OUTPUT_DIR, f"{title}.mobi")
    p = subprocess.Popen(["/usr/bin/ebook-convert", temp_file, out_file], stdout=None)
    os.remove(temp_file)


def get_param(request, key):
    param = request.form.get(key)
    if param is None:
        param = request.args.get(key)

    return param


def extract_download_link(id):
    response = httpx.get(f"{base_url}/md5/{id}")
    if response.status_code != 200:
        return None

    doc = html.fromstring(response.text)

    for link in doc.xpath('//div[@id="md5-panel-downloads"]/div/ul/li/a[contains(@class, "js-download-link")]'):
        url = link.get('href')
        if url[0] == '/':
            url = base_url + url
        link_text = ''.join(link.itertext())
        if link_text == 'Bulk torrent downloads':
            continue

        dl_url = None
        if link_text == 'Libgen.li':
            dl_url = get_libgen_link(url, True)
        elif link_text == 'Libgen.rs Fiction' and link_text == 'Libgen.rs Non-Fiction':
            dl_url = get_libgen_link(url, False)

        if dl_url is not None:
            return dl_url

    return None


def get_libgen_link(url: str, add_prefix: bool) -> str:
    resp = httpx.get(url, headers=headers)
    if resp.status_code != 200:
        return None

    doc = html.fromstring(resp.text)
    scheme, _, host, _ = url.split('/', 3)
    url = ''.join(doc.xpath('//a[h2[text()="GET"]]/@href'))
    if add_prefix:
        return f"{scheme}//{host}/{url}"
    else:
        return url


def extract_text(xpath_results, allow_none: bool = False):
    if isinstance(xpath_results, list):
        result = ''
        for e in xpath_results:
            result = result + (extract_text(e) or '')
        return result.strip()
    if isinstance(xpath_results, ElementBase):
        text: str = html.tostring(xpath_results, encoding='unicode', method='text', with_tail=False)
        text = text.strip().replace('\n', ' ')
        return ' '.join(text.split())
    if isinstance(xpath_results, (_ElementStringResult, _ElementUnicodeResult, str, Number, bool)):
        return str(xpath_results)
    if xpath_results is None and allow_none:
        return None
    if xpath_results is None and not allow_none:
        raise ValueError('extract_text(None, allow_none=False)')
    raise ValueError('unsupported type')


def get_result(result):
    item = {
        'id': extract_text(result.xpath("./@href")).replace("/md5/", ""),
        'title': extract_text(result.xpath(".//h3/text()[1]")),
        'author': extract_text(result.xpath(".//div[contains(@class, 'text-sm')]")),
        'description': extract_text(result.xpath(".//div[contains(@class, 'text-xs')]")),
    }

    item['extension'] = item['description'].split(', ')[1]
    item['title_query'] = quote_plus(item['title'])

    return item


def extract_search_results(html_plain):
    results = []

    doc = html.fromstring(html_plain)
    for result in doc.xpath("//main//div[contains(@class, 'h-[125]')]/a"):
        results.append(get_result(result))

    for item in doc.xpath('//main//div[contains(@class, "js-scroll-hidden")]'):
        result = html.fromstring(item.xpath('./comment()')[0].text)
        results.append(get_result(result))

    return results


def delete_old_outputs():
    for file in os.listdir(OUTPUT_DIR):
        filestamp = os.stat(os.path.join(OUTPUT_DIR, file)).st_mtime
        if filestamp > HOUR_DELAY * 60 * 60 * 1000:
            os.remove(os.path.join(OUTPUT_DIR, file))


def deletion_worker():
    while True:
        delete_old_outputs()

        dt = datetime.now() + timedelta(hours=HOUR_DELAY)

        while datetime.now() < dt:
            time.sleep(1)


if __name__ == "__main__":
    if HOUR_DELAY > 0:
        threading.Thread(target=deletion_worker).start()

    app.run()
