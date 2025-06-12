import os
from apify_client import ApifyClient
import requests
import base64
from openai import OpenAI

# ========== НАСТРОЙКИ ==========
APIFY_TOKEN = "apify_api_4D9qJdkLy0tymzPxD8l8O4zhXclafb2wLRHY"
INSTAGRAM_URL = "https://www.instagram.com/aimerkoshmambetov/"
OPENAI_API_KEY = "sk-5XBRs-SSoSScHCXPeRij8JvO_KXHT2mc_Y6n0e7M7qT3BlbkFJvyiweBPGWuzj_fLKGCPw8eKnVN2Scd5gUW7NLaEycA"  # <-- впиши свой OpenAI API-ключ

# ========== ИНИЦИАЛИЗАЦИЯ ==========
client = ApifyClient(APIFY_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# ========== ПОЛУЧАЕМ ПОСТЫ ==========
run_input = {
    "directUrls": [INSTAGRAM_URL],
    "resultsType": "posts",
    "resultsLimit": 3,  # сколько постов анализировать
    "searchType": "user",  # <-- это правильно!
    "addParentData": False,
}

run = client.actor("apify/instagram-scraper").call(run_input=run_input)

dataset_id = run["defaultDatasetId"]

# ========== ФУНКЦИИ ==========
def download_media(url, filename):
    r = requests.get(url)
    r.raise_for_status()
    with open(filename, "wb") as f:
        f.write(r.content)
    return filename

def analyze_text(text):
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Ты — эксперт-психолог и культуролог. Проанализируй Instagram пост по критериям: интересы, тип личности (например, MBTI, Big Five), склонность к диалогу, ценности. Ответь структурировано: \n- Интересы\n- Тип личности\n- Склонность к диалогу\n- Ценности"},
            {"role": "user", "content": text}
        ]
    )
    return response.choices[0].message.content.strip()

def analyze_image(filepath):
    with open(filepath, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Ты — эксперт-психолог и культуролог. Проанализируй Instagram изображение по критериям: интересы, тип личности (например, MBTI, Big Five), склонность к диалогу, ценности. Ответь структурировано: \n- Интересы\n- Тип личности\n- Склонность к диалогу\n- Ценности"},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}}
                ]
            }
        ]
    )
    return response.choices[0].message.content.strip()


# ========== ОСНОВНОЙ КОД ==========
text_analyses = []
image_analyses = []

for item in client.dataset(dataset_id).iterate_items():
    print(f"\nПост: {item.get('url')}")
    # Анализ текста поста
    caption = item.get("caption", "")
    if caption:
        print("Текст поста:", caption)
        analysis = analyze_text(caption)
        print("Анализ текста:\n", analysis)
        text_analyses.append(analysis)
    # Анализ картинки
    if item.get("displayUrl") and not item.get("isVideo", False):
        img_url = item["displayUrl"]
        filename = f"post_{item['id']}.jpg"
        download_media(img_url, filename)
        print("Анализ изображения:")
        img_analysis = analyze_image(filename)
        print(img_analysis)
        image_analyses.append(img_analysis)
    # Видео (если нужно — можно реализовать анализ кадра)
    elif item.get("videoUrl"):
        print(f"Видео поста: {item['videoUrl']} (анализ видео не реализован)")

# ========== ОБОБЩЁННЫЙ ПСИХОЛОГИЧЕСКИЙ ПОРТРЕТ ==========
if text_analyses or image_analyses:
    summary_prompt = (
        "Вот набор анализов постов и изображений пользователя Instagram. "
        "Составь общий психологический портрет владельца аккаунта и проквалифицируй его по критериям:\n"
        "- Интересы\n- Тип личности (например, MBTI, Big Five)\n- Склонность к диалогу\n- Ценности\n"
        "Дай краткие аргументы для каждого пункта.\n\n"
        "Анализы:\n" + "\n\n".join(text_analyses + image_analyses)
    )
    summary = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Ты — эксперт-психолог и культуролог."},
            {"role": "user", "content": summary_prompt}
        ]
    )
    print("\n\n==== Финальный психологический портрет пользователя ====")
    print(summary.choices[0].message.content.strip())
else:
    print("Нет данных для анализа.")
