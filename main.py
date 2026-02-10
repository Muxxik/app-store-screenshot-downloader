import requests
import os
import re

from google_play_scraper import app as gplay_app, search as gplay_search

# Настройки
MIN_FILE_SIZE = 1500  # 1.5 KB

# --- Общие утилиты ---

def get_high_res_url(url: str) -> str:
    """Попытка улучшить качество изображения через URL."""
    # Google Play: добавляем =w0 для оригинального размера
    if 'play-lh.googleusercontent.com' in url:
        # Убираем существующий суффикс размера, если есть
        url = re.sub(r'=w\d+.*$', '', url)
        return url + '=w0'
    # Apple: заменяем или добавляем суффикс размера
    if re.search(r'/[0-9]+x[0-9]+', url):
        return re.sub(r'/[0-9]+x[0-9]+[^/]*', '/1284x2778bb.jpg', url)
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
    """Проверяет, похожа ли ссылка на скриншот (а не на иконку/баннер/плейсхолдер)."""
    skip_patterns = [
        'AppIcon', 'favicon', 'Placeholder', 'Features',
        'marketing', 'PurpleVideo', '{w}x{h}',
    ]
    if any(p in url for p in skip_patterns):
        return False
    base = get_base_image_path(url)
    if not re.search(r'\.(png|jpg|jpeg|webp)$', base, re.IGNORECASE):
        return False
    return True


def dedup_urls(raw_urls: list[str]) -> list[str]:
    """Удаление дубликатов с сохранением порядка.

    Для Apple — дедупликация по базовому пути (без суффикса размера).
    Для Google Play — по полному URL.
    """
    seen = set()
    result = []
    for url in raw_urls:
        key = get_base_image_path(url)
        if key not in seen:
            result.append(url)
            seen.add(key)
    return result


def download_images(urls: list[str], folder_name: str) -> None:
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

            ext = "jpg"
            if b"PNG" in r.content[:8]: ext = "png"
            elif b"WEBP" in r.content[:20]: ext = "webp"

            filename = f"{folder_name}/screen_{saved_count + 1}.{ext}"

            with open(filename, 'wb') as f:
                f.write(r.content)

            print(f"    [+] {filename} ({len(r.content)//1024} KB)")
            saved_count += 1

        except Exception as e:
            print(f"    [!] Ошибка: {e}")

    print(f"--- Готово. Скачано файлов: {saved_count}\n")


# --- App Store ---

def get_appstore_data(query: str, country: str) -> dict | None:
    """Запрос к iTunes API."""
    headers = {'User-Agent': 'Mozilla/5.0'}
    if query.isdigit():
        url = f"https://itunes.apple.com/lookup?id={query}&country={country}"
    else:
        url = f"https://itunes.apple.com/search?term={query}&entity=software&limit=1&country={country}"

    try:
        res = requests.get(url, headers=headers).json()
        return res['results'][0] if res.get('resultCount', 0) > 0 else None
    except Exception:
        return None


def parse_appstore_web(url: str) -> list[str]:
    """Парсинг страницы App Store (fallback если API пуст)."""
    print("   [i] API пуст. Перехожу к сканированию сайта...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                      'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15'
    }
    try:
        html = requests.get(url, headers=headers).text
        links = re.findall(
            r'https://is[0-9]-ssl\.mzstatic\.com/image/thumb/[^\s"]+\.(?:jpg|png|webp)', html
        )
        links = [u for u in links if is_screenshot_url(u)]
        return links
    except Exception as e:
        print(f"Ошибка сайта: {e}")
        return []


def process_appstore(query: str, country: str) -> None:
    """Полный пайплайн для App Store."""
    data = get_appstore_data(query, country)
    if not data:
        print(f"[!] Приложение не найдено в App Store ({country.upper()}).")
        return

    clean_name = "".join(
        x for x in data.get('trackName', 'App') if x.isalnum() or x in "._- "
    ).replace(" ", "_")
    folder = f"{clean_name}_{country}_appstore"

    print(f"\nЦель: {clean_name} ({country.upper()}) -> Папка: {folder}")

    raw_urls = []
    keys_priority = ['screenshotUrls', 'ipadScreenshotUrls',
                     'appletvScreenshotUrls', 'macScreenshotUrls']

    found_in_api = False
    for k in keys_priority:
        current_list = data.get(k, [])
        if current_list:
            raw_urls.extend(current_list)
            found_in_api = True

    if found_in_api:
        print(f"   [i] Найдено в API: {len(raw_urls)} шт.")
    else:
        web_url = data.get('trackViewUrl')
        if web_url:
            raw_urls.extend(parse_appstore_web(web_url))

    download_images(dedup_urls(raw_urls), folder)


# --- Google Play ---

def get_gplay_data(query: str, country: str) -> dict | None:
    """Поиск приложения в Google Play.

    Принимает package name (com.example.app) или текстовый запрос.
    """
    # Если query — package name, запрашиваем напрямую
    if '.' in query and ' ' not in query:
        try:
            return gplay_app(query, lang='en', country=country)
        except Exception:
            return None

    # Текстовый поиск
    try:
        results = gplay_search(query, lang='en', country=country, n_hits=1)
        if not results:
            return None

        result = results[0]
        app_id = result.get('appId')

        # Если appId найден — получаем полные данные
        if app_id:
            try:
                return gplay_app(app_id, lang='en', country=country)
            except Exception:
                return result

        # appId=None (бывает у некоторых приложений) — ищем package name в HTML
        html = requests.get(
            f'https://play.google.com/store/search?q={query}&c=apps&hl=en&gl={country}',
            headers={'User-Agent': 'Mozilla/5.0'}
        ).text
        ids = re.findall(r'/store/apps/details\?id=([a-zA-Z0-9_.]+)', html)
        if ids:
            try:
                return gplay_app(ids[0], lang='en', country=country)
            except Exception:
                pass

        # Последний fallback — данные из поиска
        return result
    except Exception:
        return None


def process_gplay(query: str, country: str) -> None:
    """Полный пайплайн для Google Play."""
    data = get_gplay_data(query, country)
    if not data:
        print(f"[!] Приложение не найдено в Google Play ({country.upper()}).")
        return

    title = data.get('title', 'App')
    clean_name = "".join(
        x for x in title if x.isalnum() or x in "._- "
    ).replace(" ", "_")
    folder = f"{clean_name}_{country}_gplay"

    print(f"\nЦель: {clean_name} ({country.upper()}) -> Папка: {folder}")

    raw_urls = data.get('screenshots', [])
    if not raw_urls:
        print("   [!] Скриншоты не найдены.")
        return

    print(f"   [i] Найдено скриншотов: {len(raw_urls)} шт.")
    download_images(dedup_urls(raw_urls), folder)


# --- Главный цикл ---

if __name__ == "__main__":
    print("=== Screenshot Downloader v8.0 (App Store + Google Play) ===")
    print("    Значение в [скобках] — по умолчанию (просто нажмите Enter).\n")

    while True:
        query = input("\n1. Введите ID или название (exit): ").strip()
        if query.lower() in ['exit', 'quit']:
            break
        if not query:
            continue

        store = input("2. Магазин — (a)pp store / (g)oogle play [a]: ").strip().lower()
        if not store or store == 'a':
            store = 'appstore'
        elif store == 'g':
            store = 'gplay'
        else:
            print("[!] Неизвестный магазин. Используйте 'a' или 'g'.")
            continue

        country_input = input("3. Страна (us, ru, kz) [us]: ").strip().lower()
        if not country_input:
            country_input = 'us'

        if store == 'appstore':
            process_appstore(query, country_input)
        else:
            process_gplay(query, country_input)
