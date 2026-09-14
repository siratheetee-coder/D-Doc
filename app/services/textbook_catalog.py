"""Read-only, paginated search of the public OBEC textbook catalogue."""
import re
import time
from functools import lru_cache
from urllib.parse import urlencode
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler
from lxml import html

SOURCE = "http://202.29.173.190/textbook/web/index.php"

class _NoImageRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@lru_cache(maxsize=32)
def fetch_cover(filename, bucket):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}\.(?:jpg|jpeg|png|webp)', filename):
        raise ValueError('Invalid cover filename')
    url = SOURCE.rsplit('/', 1)[0] + '/images/book/' + filename
    with build_opener(_NoImageRedirect()).open(Request(url, headers={'User-Agent': 'EasyEkkasan/1.0'}), timeout=8) as response:
        data = response.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError('Cover too large')
    if data.startswith(b'\xff\xd8\xff'):
        mime = 'image/jpeg'
    elif data.startswith(b'\x89PNG\r\n\x1a\n'):
        mime = 'image/png'
    elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        mime = 'image/webp'
    else:
        raise ValueError('Unsupported cover data')
    return data, mime
CLASS_IDS = {**{f"ป.{i}": str(i) for i in range(1, 7)},
             "ม.1": "9", "ม.2": "10", "ม.3": "11", "ม.4": "13", "ม.5": "14", "ม.6": "15"}


def parse_results(content):
    tree = html.fromstring(content)
    rows = []
    for item in tree.xpath('//*[@id="result_content"]//div[@class="item"]'):
        values = {}
        for label in item.xpath('.//div[contains(concat(" ",normalize-space(@class)," ")," titleleft ")]'):
            sibling = label.getnext()
            if sibling is not None:
                values[label.text_content().strip()] = ' '.join(sibling.text_content().split())
        titles = [values[k] for k in ("หนังสือเรียน", "แบบฝึกหัด", "สื่อการเรียนรู้") if values.get(k)]
        if not titles:
            info = item.xpath('.//div[@class="infoarea"]/div[contains(@class,"objright")]')
            titles = [' '.join(info[0].text_content().split())] if info else []
        price = re.search(r"ราคา\s*([\d,.]+)\s*บาท", item.text_content())
        identifier = re.search(r"addcart\('([0-9]+)&", html.tostring(item, encoding='unicode'))
        if not titles or not price or not identifier:
            raise ValueError("รูปแบบข้อมูลหนังสือจากต้นทางเปลี่ยนไป")
        level = values.get("ชั้น", "")
        m = re.fullmatch(r"(ประถม|มัธยม)ศึกษาปีที่\s*([1-6])", level)
        images = item.xpath('./div[@class="image"]/img/@src')
        cover = re.fullmatch(r'images/book/([A-Za-z0-9_-]{1,100}\.(?:jpg|jpeg|png|webp))', images[0]) if images else None
        rows.append({"title": titles[0], "price": float(price.group(1).replace(',', '')),
                     "publisher": values.get("ผู้จัดพิมพ์", ""), "subject": values.get("กลุ่มสาระการเรียนรู้", ""),
                     "level": (('ป.' if m[1] == 'ประถม' else 'ม.') + m[2]) if m else '',
                     "source_level": level, "publication": values.get("ปี พ.ศ. ที่เผยแพร่", ""),
                     "source_id": identifier[1],
                     "cover_url": '/textbooks/purchase/catalog/cover/' + cover[1] if cover else ''})
    if not tree.xpath('//*[@id="result_content"]'):
        raise ValueError("ไม่พบผลค้นหาจากฐานข้อมูลต้นทาง")
    pages = re.search(r"หน้าที่\s*(\d+)\s*จาก\s*(\d+)\s*หน้า", tree.text_content())
    filters = {}
    for key, field in [('subjects', 'bookgroup'), ('publishers', 'bookprint')]:
        filters[key] = [{'id': node.get('value'), 'label': ' '.join(node.xpath('ancestor::tr[1]')[0].text_content().split())}
                        for node in tree.xpath('//input[@name="' + field + '[]"]')]
    filters['rounds'] = [{'id': node.get('value'), 'label': ' '.join(node.text_content().split())}
                         for node in tree.xpath('//select[@name="id_round"]/option[@value!=""]')]
    return {"items": rows, "pages": int(pages[2]) if pages else 1, "filters": filters}


@lru_cache(maxsize=64)
def _search(query, level, page, bucket, subject='', publisher='', publication=''):
    params = {'bookmain': '11,12', 'name': query, 'class': CLASS_IDS.get(level, ''),
              'chksearch': 'true', 'ispage': page, 'bookgroup': subject,
              'bookprint': publisher, 'id_round': publication}
    url = SOURCE + '?' + urlencode(params)
    # The URL is fixed: no user-provided host, path, or external credentials.
    with urlopen(Request(url, headers={'User-Agent': 'EasyEkkasan/1.0'}), timeout=12) as response:
        content = response.read(2_000_001)
    if len(content) > 2_000_000:
        raise ValueError("ผลค้นหาจากต้นทางมีขนาดเกินกำหนด")
    return {**parse_results(content.decode('utf-8')), "source_url": url, "page": page,
            "fetched_at": int(time.time())}


def search_catalog(query, level, page, subject='', publisher='', publication='', refresh=False):
    filters = [value if re.fullmatch(r'[0-9]{1,10}', value or '') else ''
               for value in (subject, publisher, publication)]
    search = _search.__wrapped__ if refresh else _search
    return search(query.strip()[:100], level, min(max(page, 1), 1000), int(time.time() // 300), *filters)
