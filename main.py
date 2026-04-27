import requests
import os
import re

from google_play_scraper import app as gplay_app, search as gplay_search

# Настройки
MIN_FILE_SIZE = 1500  # 1.5 KB

# Карта country -> language для App Store URL (?l=<язык>).
# Без этого параметра Apple часто возвращает дефолтные/английские ассеты,
# даже если у приложения есть локализованные скриншоты для этой страны.
COUNTRY_LANG: dict[str, str] = {
    # English-speaking
    'us': 'en-US', 'gb': 'en-GB', 'ca': 'en-CA', 'au': 'en-AU',
    'nz': 'en-NZ', 'ie': 'en-IE', 'sg': 'en-SG', 'in': 'en-IN',
    'ph': 'en-PH', 'my': 'en-MY', 'hk': 'en-HK', 'za': 'en-ZA',
    # CIS / Russian-speaking
    'ru': 'ru', 'kz': 'ru', 'by': 'ru',
    'ua': 'uk',
    # Asia
    'vn': 'vi', 'jp': 'ja', 'kr': 'ko',
    'cn': 'zh-Hans-CN', 'tw': 'zh-Hant-TW',
    'th': 'th', 'id': 'id',
    # Europe
    'de': 'de-DE', 'at': 'de-DE', 'ch': 'de-DE',
    'fr': 'fr-FR', 'be': 'fr-FR',
    'es': 'es-ES', 'it': 'it',
    'pt': 'pt-PT', 'br': 'pt-BR',
    'mx': 'es-MX', 'ar': 'es-MX', 'cl': 'es-MX', 'co': 'es-MX',
    'tr': 'tr', 'pl': 'pl', 'nl': 'nl',
    'se': 'sv', 'no': 'nb', 'dk': 'da', 'fi': 'fi',
    'cz': 'cs', 'sk': 'sk', 'hu': 'hu',
    'ro': 'ro', 'gr': 'el',
    # Middle East
    'il': 'he',
    'sa': 'ar', 'ae': 'ar', 'eg': 'ar',
}


def _with_lang(url: str, lang: str | None) -> str:
    """Дописывает к URL ?l=<lang> (или &l=<lang>, если уже есть query string)."""
    if not lang:
        return url
    sep = '&' if '?' in url else '?'
    return f"{url}{sep}l={lang}"


def _short_lang(lang: str) -> str:
    """Возвращает короткий код языка: 'en-US' -> 'en', 'zh-Hans-CN' -> 'zh'."""
    return lang.split('-')[0] if lang else 'en'


def _clean_folder(folder_name: str, prefixes: tuple[str, ...]) -> None:
    """Удаляет файлы по префиксам в папке (чтобы не оставались артефакты прошлых прогонов)."""
    if not os.path.isdir(folder_name):
        return
    for fname in os.listdir(folder_name):
        if any(fname.startswith(p) for p in prefixes):
            try:
                os.remove(os.path.join(folder_name, fname))
            except OSError:
                pass


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
    _clean_folder(folder_name, ('screen_',))
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

def extract_appstore_id(query: str) -> str | None:
    """Если в строке встречается App Store ID (idXXXXXXXX или просто длинное число),
    возвращает его. Поддерживает форматы:
      - 1534886813
      - id1534886813
      - https://apps.apple.com/us/app/.../id1534886813
      - https://apps.apple.com/ru/app/.../id1534886813?...
    """
    m = re.search(r'(?:^|/|id)(\d{8,12})(?:\D|$)', query)
    return m.group(1) if m else None


def get_appstore_data(query: str, country: str) -> dict | None:
    """Запрос к iTunes API. Принимает чистый ID, 'idXXXX' или App Store URL."""
    headers = {'User-Agent': 'Mozilla/5.0'}
    app_id = extract_appstore_id(query) if not query.isdigit() else query
    if query.isdigit() or app_id:
        url = f"https://itunes.apple.com/lookup?id={app_id or query}&country={country}"
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


def _fetch_m3u8(url: str) -> list[str]:
    """Возвращает все .m3u8 ссылки с одной версии страницы App Store."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                      'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15'
    }
    try:
        html = requests.get(url, headers=headers, timeout=15).text
    except Exception as e:
        print(f"   [!] Ошибка загрузки {url}: {e}")
        return []
    # В JSON-данных слэши экранированы — нормализуем
    text = re.sub(r'\\u002[fF]', '/', html)
    text = text.replace('\\/', '/')
    return re.findall(r'https://[^\s"\\<>]+?\.m3u8', text)


def parse_appstore_videos(url: str) -> list[str]:
    """Извлекает ссылки на HLS-плейлисты (.m3u8) видео-превью со страницы App Store.

    iTunes Lookup API не отдаёт видео — данные лежат в JSON внутри HTML-страницы.
    Превью для iPhone и iPad живут на разных версиях страницы (по умолчанию и
    с ?platform=ipad), поэтому фетчим обе и склеиваем уникальные ссылки.
    """
    sep = '&' if '?' in url else '?'
    variants = [('iPhone', url), ('iPad', f"{url}{sep}platform=ipad")]

    seen: set[str] = set()
    result: list[str] = []
    for label, v in variants:
        new_for_variant = 0
        for u in _fetch_m3u8(v):
            if u not in seen:
                seen.add(u)
                result.append(u)
                new_for_variant += 1
        print(f"   [i] {label}: уникальных видео-ссылок {new_for_variant}")
    return result


def download_videos(urls: list[str], folder_name: str) -> None:
    """Скачивает HLS-видео и собирает в .mp4 через ffmpeg (без перекодирования)."""
    import shutil
    import subprocess

    if not urls:
        print("--- Видео-превью не найдено.")
        return

    if not shutil.which('ffmpeg'):
        print("--- [!] Найдено видео-превью, но ffmpeg не установлен — пропускаю.")
        print("    Установите: 'brew install ffmpeg' (macOS) или 'apt install ffmpeg' (Linux).")
        return

    os.makedirs(folder_name, exist_ok=True)
    _clean_folder(folder_name, ('preview_',))
    print(f"--- Видео-превью: найдено {len(urls)} шт. Скачиваю через ffmpeg...")

    saved = 0
    for url in urls:
        out_path = f"{folder_name}/preview_{saved + 1}.mp4"
        cmd = [
            'ffmpeg', '-y', '-loglevel', 'error',
            '-i', url,
            '-c', 'copy',
            '-bsf:a', 'aac_adtstoasc',
            out_path,
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if (res.returncode == 0
                    and os.path.exists(out_path)
                    and os.path.getsize(out_path) > 10_000):
                size_kb = os.path.getsize(out_path) // 1024
                print(f"    [+] {out_path} ({size_kb} KB)")
                saved += 1
            else:
                err_lines = (res.stderr or '').strip().splitlines()
                err = err_lines[-1] if err_lines else 'неизвестная ошибка'
                print(f"    [!] Не удалось скачать видео: {err}")
                # Подчищаем пустой/битый файл
                if os.path.exists(out_path) and os.path.getsize(out_path) <= 10_000:
                    os.remove(out_path)
        except subprocess.TimeoutExpired:
            print(f"    [!] Таймаут (>180с) при скачивании {url}")
        except Exception as e:
            print(f"    [!] Ошибка: {e}")

    print(f"--- Видео скачано: {saved}\n")


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

    # К URL страницы приклеиваем ?l=<lang> по стране — иначе Apple часто
    # отдаёт дефолтные/английские ассеты вместо локализованных.
    web_url = data.get('trackViewUrl')
    lang = COUNTRY_LANG.get(country.lower(), 'en')
    web_url = _with_lang(web_url, lang) if web_url else None

    if found_in_api:
        print(f"   [i] Найдено в API: {len(raw_urls)} шт.")
    elif web_url:
        raw_urls.extend(parse_appstore_web(web_url))

    download_images(dedup_urls(raw_urls), folder)

    # Видео-превью — iTunes API их не отдаёт, всегда парсим страницу
    if web_url:
        download_videos(parse_appstore_videos(web_url), folder)


# --- Google Play ---

def extract_gplay_id(query: str) -> str | None:
    """Извлекает package name (com.example.app) из строки.

    Поддерживает форматы:
      - com.example.app
      - https://play.google.com/store/apps/details?id=com.example.app
      - https://play.google.com/store/apps/details?id=com.example.app&hl=en&gl=ru
    """
    # 1) Параметр id=... в URL (даже если в строке мусор вокруг)
    m = re.search(r'[?&]id=([a-zA-Z][a-zA-Z0-9_.]+)', query)
    if m:
        return m.group(1)
    # 2) Сама строка похожа на package name (reverse-domain)
    if re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)+', query):
        return query
    return None


def get_gplay_data(query: str, country: str) -> dict | None:
    """Поиск приложения в Google Play.

    Принимает package name (com.example.app), URL Google Play или текстовый запрос.
    Язык определяется по стране через COUNTRY_LANG — иначе вернутся английские
    скриншоты, даже если у приложения есть локализованные ассеты.
    """
    lang = _short_lang(COUNTRY_LANG.get(country.lower(), 'en'))

    # Если в строке есть package name (явный или внутри URL) — запрашиваем напрямую
    pkg = extract_gplay_id(query)
    if pkg:
        try:
            return gplay_app(pkg, lang=lang, country=country)
        except Exception:
            return None

    # Текстовый поиск
    try:
        results = gplay_search(query, lang=lang, country=country, n_hits=1)
        if not results:
            return None

        result = results[0]
        app_id = result.get('appId')

        # Если appId найден — получаем полные данные
        if app_id:
            try:
                return gplay_app(app_id, lang=lang, country=country)
            except Exception:
                return result

        # appId=None (бывает у некоторых приложений) — ищем package name в HTML
        html = requests.get(
            f'https://play.google.com/store/search?q={query}&c=apps&hl={lang}&gl={country}',
            headers={'User-Agent': 'Mozilla/5.0'}
        ).text
        ids = re.findall(r'/store/apps/details\?id=([a-zA-Z0-9_.]+)', html)
        if ids:
            try:
                return gplay_app(ids[0], lang=lang, country=country)
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

        country_input = input("3. Страна (us, ru, de) [us]: ").strip().lower()
        if not country_input:
            country_input = 'us'

        if store == 'appstore':
            process_appstore(query, country_input)
        else:
            process_gplay(query, country_input)
