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
    new_url = re.sub(r'/[0-9]+x[0-9]+[^/]*', '/1284x2778bb', url)
    return new_url

def parse_web_page(url):
    """Парсинг сайта (возвращает список в том порядке, как они в коде страницы)"""
    print("   [i] API пуст. Перехожу к сканированию сайта...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15'
    }
    try:
        html = requests.get(url, headers=headers).text
        # Ищем картинки. re.findall возвращает список В ПОРЯДКЕ их нахождения в тексте
        links = re.findall(r'https://is[0-9]-ssl\.mzstatic\.com/image/thumb/[^"]+\.(?:jpg|png|webp)', html)
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
            
            if 'AppIcon' in url or 'favicon' in url:
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
        # Мы не используем set(), потому что он перемешивает данные.
        # Мы используем цикл с проверкой seen.
        seen = set()
        ordered_unique_urls = []
        for url in raw_urls:
            if url not in seen:
                ordered_unique_urls.append(url)
                seen.add(url)
        
        download_images(ordered_unique_urls, full_folder_name)