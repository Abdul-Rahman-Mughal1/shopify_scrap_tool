import os
import re
import json
import time
import datetime
import requests
import pandas as pd
from bs4 import BeautifulSoup
from PIL import Image
from io import BytesIO
from urllib.parse import urlparse

### ----------------- CONFIG -----------------
COLLECTION_URL = "https://shaziaraufkhanofficial.com/collections/celeste"
BASE_DOMAIN = "https://shaziaraufkhanofficial.com"
def get_images_root():
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = os.path.join("static", "downloads", f"images_{ts}")
    os.makedirs(folder, exist_ok=True)
    return folder
OUTPUT_EXCEL = os.path.join("static", "downloads", "products.xlsx")
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
}
SLEEP_BETWEEN_REQUESTS = 0.4  # be polite
### ------------------------------------------

# os.makedirs(OUTPUT_FOLDER, exist_ok=True)

def safe_filename(s):
    return re.sub(r'[^A-Za-z0-9_\-\.]', '_', s)[:200]

def normalize_price(p):
    try:
        if p is None or p == "":
            return ""
        # If numeric as string
        if isinstance(p, str):
            p = p.replace(',', '').strip()
            if p == "":
                return ""
            if re.match(r'^\d+(\.\d+)?$', p):
                p = float(p) if '.' in p else int(p)
            else:
                return p
        # If looks very large (e.g. 9500000) it may be in cents -> divide by 100
        if isinstance(p, (int, float)) and p > 100000:
            return int(p / 100) if int(p) == p else (p / 100)
        return p
    except Exception:
        return p

def extract_srcset_url(s):
    if not s:
        return ""
    # choose the largest width url (last entry)
    parts = [p.strip() for p in s.split(',') if p.strip()]
    if not parts:
        return s.strip()
    last = parts[-1]
    url = last.split()[0]
    return url

def absolutize_url(u):
    if not u:
        return ""
    u = u.replace('\\/', '/')
    u = u.strip()
    if u.startswith('//'):
        return 'https:' + u
    if u.startswith('/'):
        return BASE_DOMAIN + u
    if u.startswith('http://') or u.startswith('https://'):
        return u
    # fallback
    return u

def download_image(img_url, folder, name):
    try:
        if not img_url:
            return ""
        img_url = absolutize_url(img_url)
        r = requests.get(img_url, headers=REQUEST_HEADERS, timeout=20)
        r.raise_for_status()
        img_path = os.path.join(folder, safe_filename(name) + ".webp")
        Image.open(BytesIO(r.content)).convert("RGB").save(img_path, "webp")
        return img_path
    except Exception as e:
        print("   ❌ image download failed:", img_url, "->", e)
        return ""

def find_product_json(psoup):
    # 1. script with data-product attribute (preferred)
    tag = psoup.find('script', attrs={'data-product': True})
    if tag and tag.string:
        try:
            return json.loads(tag.string)
        except Exception:
            pass

    # 2. script[type="application/json"] blocks (common)
    for tag in psoup.find_all('script', type='application/json'):
        txt = (tag.string or "").strip()
        if not txt:
            continue
        if '"variants"' in txt or '"product"' in txt:
            try:
                data = json.loads(txt)
                # if wrapper with 'product'
                if isinstance(data, dict) and 'product' in data and isinstance(data['product'], dict):
                    return data['product']
                return data
            except Exception:
                pass

    # 3. try to extract `var meta = {...};` style JS object and parse JSON inside
    for tag in psoup.find_all('script'):
        txt = tag.string or ""
        if 'var meta' in txt and 'product' in txt:
            m = re.search(r'var\s+meta\s*=\s*({)', txt)
            if m:
                start = m.start(1)
                # bracket matching
                cnt = 0
                end = None
                for i in range(start, len(txt)):
                    if txt[i] == '{':
                        cnt += 1
                    elif txt[i] == '}':
                        cnt -= 1
                        if cnt == 0:
                            end = i + 1
                            break
                if end:
                    snippet = txt[start:end]
                    try:
                        data = json.loads(snippet)
                        if isinstance(data, dict) and 'product' in data:
                            return data['product']
                        return data
                    except Exception:
                        # continue to other fallbacks
                        pass

    # 4. fallback: search for window.ShopifyAnalytics.meta assignment
    for tag in psoup.find_all('script'):
        txt = tag.string or ""
        if 'ShopifyAnalytics.meta' in txt and 'product' in txt:
            m = re.search(r'var\s+meta\s*=\s*({)', txt)
            if m:
                start = m.start(1)
                cnt = 0
                end = None
                for i in range(start, len(txt)):
                    if txt[i] == '{':
                        cnt += 1
                    elif txt[i] == '}':
                        cnt -= 1
                        if cnt == 0:
                            end = i + 1
                            break
                if end:
                    snippet = txt[start:end]
                    try:
                        data = json.loads(snippet)
                        if isinstance(data, dict) and 'product' in data:
                            return data['product']
                        return data
                    except Exception:
                        pass
    return None

def parse_collection_links(collection_html):
    soup = BeautifulSoup(collection_html, "html.parser")
    # primary method: div.sr4-product -> data-product-options
    cards = soup.find_all("div", class_="sr4-product")
    links = []
    for c in cards:
        data_raw = c.get("data-product-options") or ""
        if data_raw:
            try:
                info = json.loads(data_raw.replace("'", '"'))
                handle = info.get("handle")
                if handle:
                    links.append(f"{BASE_DOMAIN}/products/{handle}")
                    continue
            except Exception:
                pass
        # fallback: find anchor inside card
        a = c.find("a", href=True)
        if a:
            href = a['href']
            if href.startswith('/'):
                links.append(BASE_DOMAIN + href)
            else:
                links.append(href)
    # last fallback: any product link anchors
    if not links:
        for a in soup.select('a[href*="/products/"]'):
            href = a['href']
            if href.startswith('/'):
                links.append(BASE_DOMAIN + href)
            else:
                links.append(href)
    # dedupe while preserving order
    seen = set()
    ordered = []
    for l in links:
        if l not in seen:
            seen.add(l)
            ordered.append(l)
    return ordered

def scrape_collection(collection_url):
    global BASE_DOMAIN
    parsed = urlparse(collection_url)
    BASE_DOMAIN = f"{parsed.scheme}://{parsed.netloc}"

    print("Fetching collection:", collection_url)
    r = requests.get(collection_url, headers=REQUEST_HEADERS, timeout=20)
    r.raise_for_status()
    links = parse_collection_links(r.text)
    print(f"Found {len(links)} product links in collection.")
    return links


def scrape(collection_url):
    images_root = get_images_root()
    product_links = scrape_collection(collection_url)
    records = []
    for idx, url in enumerate(product_links, 1):
        try:
            print(f"\n[{idx}/{len(product_links)}] Visiting: {url}")
            r = requests.get(url, headers=REQUEST_HEADERS, timeout=20)
            r.raise_for_status()
            psoup = BeautifulSoup(r.text, "html.parser")
            time.sleep(SLEEP_BETWEEN_REQUESTS)

            # product handle from URL
            handle = url.rstrip('/').split('/')[-1]

            # try to get product JSON (preferred)
            product_json = find_product_json(psoup) or {}

            # Title (prefer JSON)
            title = ""
            if isinstance(product_json, dict):
                title = product_json.get("title") or product_json.get("name") or ""
            if not title:
                # fallback to various H1 selectors
                title_tag = psoup.find("h1", class_="product__title") or psoup.find("h1", class_="product-title") or psoup.find("h1")
                title = title_tag.get_text(strip=True) if title_tag else handle

            # Description (prefer JSON)
            # --- DESCRIPTION ---
            description = ""

            # 1. JSON se
            if isinstance(product_json, dict):
                description = (
                    product_json.get("description")
                    or product_json.get("body_html")
                    or product_json.get("product_description")
                    or ""
                )

            # 2. Page ke common selectors se
            if not description:
                desc_tag = (
                    psoup.find("div", class_="sr4-product__description")
                    or psoup.find("div", class_="product__description")
                    or psoup.find("div", id="ProductDetails")
                )
                if desc_tag:
                    description = desc_tag.get_text(" ", strip=True)

            # 3. Meta description fallback
            if not description:
                meta_desc = psoup.find("meta", {"name": "description"})
                if meta_desc:
                    description = meta_desc.get("content", "").strip()
                    
            # --- SKU / Design Code ---
            sku = ""
            sku_tag = psoup.find("div", class_="sr4-barcode-wrapper")
            if sku_tag:
                val = sku_tag.find("span", {"data-product__barcode-number": True})
                if val:
                    sku = val.get_text(strip=True)

            # collect image URLs (from JSON and from page tags)
            image_urls = []

            # from product_json 'images' or variants' image
            try:
                if isinstance(product_json, dict):
                    imgs = product_json.get("images") or product_json.get("media") or []
                    if isinstance(imgs, list):
                        for it in imgs:
                            if isinstance(it, str):
                                image_urls.append(it)
                            elif isinstance(it, dict):
                                # different shapes -> find src / url / image fields
                                url_candidate = it.get("src") or it.get("url") or it.get("image") or it.get("originalSrc")
                                if url_candidate:
                                    image_urls.append(url_candidate)
            except Exception:
                pass

            # from variant objects inside product_json
            try:
                if isinstance(product_json, dict):
                    for v in product_json.get("variants", []) or []:
                        iv = v.get("image") if isinstance(v, dict) else None
                        if iv and isinstance(iv, dict):
                            src = iv.get("src") or iv.get("url")
                            if src:
                                image_urls.append(src)
                        elif isinstance(iv, str):
                            image_urls.append(iv)
            except Exception:
                pass

            # from <img data-master> and data-srcset on page
            img_tags = psoup.select("img[data-master], img[data-srcset], img[srcset], img[src]")
            for img in img_tags:
                datam = img.get("data-master") or img.get("data-srcset") or img.get("srcset") or img.get("src") or ""
                if datam:
                    # if srcset-like, extract largest url
                    if ',' in datam:
                        url_candidate = extract_srcset_url(datam)
                    else:
                        url_candidate = datam
                    image_urls.append(url_candidate)

            # clean and absolutize list, dedupe keeping order
            cleaned = []
            seen = set()
            for u in image_urls:
                if not u:
                    continue
                u2 = absolutize_url(str(u))
                if u2 and u2 not in seen:
                    seen.add(u2)
                    cleaned.append(u2)
            image_urls = cleaned

            # download images into product-specific folder (handle-based)
            product_folder = os.path.join(images_root, safe_filename(handle))
            os.makedirs(product_folder, exist_ok=True)
            image_paths = []
            for i_img, img_url in enumerate(image_urls, 1):
                name = f"{safe_filename(handle)}_{i_img}"
                pth = download_image(img_url, product_folder, name)
                if pth:
                    image_paths.append(pth)

            # get variants -> prefer JSON; fallback to ShopiyAnalytics/meta or page parsing
            variants = []
            if isinstance(product_json, dict) and product_json.get("variants"):
                variants = product_json.get("variants")
            else:
                # fallback: parse <select name="id">
                variant_select = psoup.find("select", {"name": "id"})
                if variant_select:
                    for opt in variant_select.find_all("option"):
                        v_id = opt.get("value", "")
                        v_title = opt.get_text(strip=True)
                        inv_qty = opt.get("data-inventoryquantity", "")
                        inv_policy = opt.get("data-inventorypolicy", "")
                        incoming = opt.get("data-incoming", "")
                        variants.append({
                            "id": v_id,
                            "title": v_title,
                            "price": "",  # will fill below
                            "compare_at_price": "",
                            "sku": "",
                            "available": inv_qty if inv_qty != "0" else "Out of stock",
                        })

            # If still no variants, create single default 'No Variant' row with product-level price if available
            if not variants:
                # try to find price in JSON or meta
                price_val = ""
                if isinstance(product_json, dict):
                    price_val = product_json.get("price") or product_json.get("variants", [{}])[0].get("price") if product_json.get("variants") else ""
                # fallback try meta price tags
                price_meta = psoup.find("meta", property="og:price:amount")
                if price_meta and not price_val:
                    price_val = price_meta.get("content", "")
                normalized = normalize_price(price_val)
                records.append({
                    "Product Title": title,
                    "Product URL": url,
                    "Description": description,
                    "Variant ID": "",
                    "Variant Title": "",
                    "Price": normalized,
                    "Compare_at_Price": "",
                    "SKU": sku,
                    "Available": "",
                    "Images": ", ".join(image_paths)
                })
            else:
                for v in variants:
                    price_raw = v.get("price") or psoup.find("meta", {"property": "og:price:amount"}).get("content", "")
                    records.append({
                        "Product Title": title,
                        "Product URL": url,
                        "Description": description,
                        "Variant ID": v.get("id", ""),
                        "Variant Title": v.get("title", ""),
                        "Price": normalize_price(price_raw),
                        "Compare_at_Price": v.get("compare_at_price", ""),
                        "SKU": v.get("sku", ""),
                        "Available": v.get("available", ""),
                        "Images": ", ".join(image_paths)
                    })

            print("   ✅ scraped:", title, "| images:", len(image_paths), "| variants rows added:", len(variants) or 1)

        except Exception as e:
            print("   ❌ Error scraping product:", url, "->", e)

    # Save to Excel
    df = pd.DataFrame(records)
    excel_path = OUTPUT_EXCEL
    try:
        df.to_excel(excel_path, index=False)
        print(f"\n🎉 Done. Saved {len(df)} rows to '{excel_path}'. Images in '{images_root}/' .")
    except PermissionError:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        excel_path = f"products_{ts}.xlsx"
        df.to_excel(excel_path, index=False)
        print(f"\n⚠️ Could not write to '{OUTPUT_EXCEL}' (file might be open). Saved to '{excel_path}' instead.")
    except Exception as e:
        print("\n❌ Failed to save Excel:", e)

    # 👇 ye line add karo
    return df, excel_path, images_root

if __name__ == "__main__":
    # Abhi ke liye manual input
    url = input("Enter collection URL: ").strip()
    scrape(url)
