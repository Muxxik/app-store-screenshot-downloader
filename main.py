import requests
import os
import re

# Настройки
MIN_FILE_SIZE = 1500  # 1.5 KB

def get_json_data(query, country):
    """Запрос к API Apple"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    if query.isdigit():
        url = f"https://itunes.apple.com/lookup?id={query}&country={country}"
    else:
        url = f"https://itunes.apple.com/search?term={query}&entity=software&limit=1&country={country}"
    
    try:
        res = requests.get(url, headers=headers).json()
        return res['results'][0] if res.get('resultCount', 0) > 0 else None
    except:
        return None

def get_high_res_url(url):
    """Попытка улучшить качество изображения через URL"""
    if re.search(r'/[0-9]+x[0-9]+', url):
        # URL уже содержит размер — заменяем на высокое разрешение
        return re.sub(r'/[0-9]+x[0-9]+[^/]*', '/1284x2778bb.jpg', url)
    # URL без размера (из JSON-LD) — добавляем суффикс
    return url + '/1284x2778bb.jpg'

def get_base_image_path(url: str) -> str:
    """Извлекает базовый путь изображения без суффикса размера Apple CDN.

    Пример: .../filename.png/300x650bb-75.webp -> .../filename.png
    """
    parts = url.rsplit('/', 1)
    if len(parts) == 2 and re.search(r'\d+x\d+', parts[1]):
        return parts[0]
    return url

def is_screenshot_url(url: str) -> bool:
    """Проверяет, похожа ли ссылка на скриншот (а не на иконку/баннер/плейсхолдер)"""
    skip_patterns = [
        'AppIcon', 'favicon', 'Placeholder', 'Features',
        'marketing', 'PurpleVideo', '{w}x{h}',
    ]
    if any(p in url for p in skip_patterns):
        return False
    # Базовый путь (без суффикса размера) должен заканчиваться на расширение картинки,
    # иначе это видео-превью или другой мусор (напр. хэш-URL без оригинального файла)
    base = get_base_image_path(url)
    if not re.search(r'\.(png|jpg|jpeg|webp)$', base, re.IGNORECASE):
        return False
    return True

def parse_web_page(url):
    """Парсинг сайта (возвращает список в том порядке, как они в коде страницы)"""
    print("   [i] API пуст. Перехожу к сканированию сайта...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15'
    }
    try:
        html = requests.get(url, headers=headers).text
        # Ищем картинки. [^\s"]+ — не захватываем пробелы (srcset) и кавычки
        links = re.findall(r'https://is[0-9]-ssl\.mzstatic\.com/image/thumb/[^\s"]+\.(?:jpg|png|webp)', html)
        # Оставляем только скриншоты
        links = [u for u in links if is_screenshot_url(u)]
        return links
    except Exception as e:
        print(f"Ошибка сайта: {e}")
        return []

def download_images(urls, folder_name):
    if not urls:
        print("--- Нет ссылок для скачивания.")
        return

    os.makedirs(folder_name, exist_ok=True)
    print(f"--- Найдено {len(urls)} ссылок. Начинаю загрузку в '{folder_name}'...")
    
    saved_count = 0
    
    for i, url in enumerate(urls):
        target_url = get_high_res_url(url)
        
        try:
            r = requests.get(target_url, timeout=10)
            
            # Если high-res не сработал, берем оригинал
            if r.status_code != 200 or len(r.content) < MIN_FILE_SIZE:
                r = requests.get(url, timeout=10)

            if len(r.content) < MIN_FILE_SIZE:
                continue
            
            if not is_screenshot_url(url):
                continue

            ext = "jpg"
            if b"PNG" in r.content[:8]: ext = "png"
            elif b"WEBP" in r.content[:20]: ext = "webp"

            # Нумерация теперь строго соответствует порядку в списке urls
            filename = f"{folder_name}/screen_{saved_count + 1}.{ext}"
            
            with open(filename, 'wb') as f:
                f.write(r.content)
            
            print(f"    [+] {filename} ({len(r.content)//1024} KB)")
            saved_count += 1
            
        except Exception as e:
            print(f"    [!] Ошибка: {e}")

    print(f"--- Готово. Скачано файлов: {saved_count}\n")

if __name__ == "__main__":
    print("=== App Store Downloader v7.0 (Strict Order) ===")
    
    while True:
        query = input("1. Введите ID или название (exit): ").strip()
        if query.lower() in ['exit', 'quit']: break
        if not query: continue
        
        country_input = input("2. Страна (us, ru, kz) [us]: ").strip().lower()
        if not country_input: 
            country_input = 'us'
        
        data = get_json_data(query, country_input)
        if not data:
            print(f"[!] Приложение не найдено в регионе '{country_input.upper()}'.")
            continue

        clean_name = "".join(x for x in data.get('trackName', 'App') if x.isalnum() or x in "._- ").replace(" ", "_")
        full_folder_name = f"{clean_name}_{country_input}"
        
        print(f"\nЦель: {clean_name} ({country_input.upper()}) -> Папка: {full_folder_name}")

        raw_urls = []
        
        # 1. API возвращает ключи в правильном логическом порядке
        # Сначала телефон, потом планшет, потом часы/ТВ
        keys_priority = ['screenshotUrls', 'ipadScreenshotUrls', 'appletvScreenshotUrls', 'macScreenshotUrls']
        
        found_in_api = False
        for k in keys_priority:
            current_list = data.get(k, [])
            if current_list:
                raw_urls.extend(current_list)
                found_in_api = True
        
        # 2. Если API пустое, идем на сайт
        if found_in_api:
             print(f"   [i] Найдено в API: {len(raw_urls)} шт.")
        else:
            web_url = data.get('trackViewUrl')
            if web_url:
                web_links = parse_web_page(web_url)
                raw_urls.extend(web_links)
            
        # 3. УДАЛЕНИЕ ДУБЛИКАТОВ С СОХРАНЕНИЕМ ПОРЯДКА
        # Дедупликация по базовому пути (без суффикса размера),
        # чтобы одна картинка в разных размерах из srcset не дублировалась.
        seen_bases = set()
        ordered_unique_urls = []
        for url in raw_urls:
            base = get_base_image_path(url)
            if base not in seen_bases:
                ordered_unique_urls.append(url)
                seen_bases.add(base)
        
        download_images(ordered_unique_urls, full_folder_name)