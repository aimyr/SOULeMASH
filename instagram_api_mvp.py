import os
from apify_client import ApifyClient
import requests
import base64
from openai import OpenAI

APIFY_TOKEN = "apify_api_4D9qJdkLy0tymzPxD8l8O4zhXclafb2wLRHY"
OPENAI_API_KEY = "sk-5XBRs-SSoSScHCXPeRij8JvO_KXHT2mc_Y6n0e7M7qT3BlbkFJvyiweBPGWuzj_fLKGCPw8eKnVN2Scd5gUW7NLaEycA"

client = ApifyClient(APIFY_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

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


def analyze_instagram_account(account_name: str, posts_limit: int = 3) -> str:
    INSTAGRAM_URL = f"https://www.instagram.com/{account_name}/"
    run_input = {
        "directUrls": [INSTAGRAM_URL],
        "resultsType": "posts",
        "resultsLimit": posts_limit,
        "searchType": "user",
        "addParentData": False,
    }
    run = client.actor("apify/instagram-scraper").call(run_input=run_input)
    dataset_id = run["defaultDatasetId"]

    text_analyses = []
    image_analyses = []

    for item in client.dataset(dataset_id).iterate_items():
        caption = item.get("caption", "")
        if caption:
            analysis = analyze_text(caption)
            text_analyses.append(analysis)
        if item.get("displayUrl") and not item.get("isVideo", False):
            img_url = item["displayUrl"]
            filename = f"post_{item['id']}.jpg"
            download_media(img_url, filename)
            img_analysis = analyze_image(filename)
            image_analyses.append(img_analysis)

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
        return summary.choices[0].message.content.strip()
    else:
        return "Нет данных для анализа."

# ==== Example usage ====
if __name__ == "__main__":
    account = "aimerkoshmambetov"
    print(analyze_instagram_account(account))
