"""Helper script: creates a clean config.json without personal tokens."""
import json

template = {
    "vk": {"user_token": "", "group_token": "", "group_id": "", "api_version": "5.131"},
    "sources": [],
    "download_settings": {"posts_to_download": 100, "batch_size": 100, "delay_between_requests": 1, "check_duplicates": True},
    "publishing_settings": {"posts_to_publish": 50, "publish_delay": 3600, "postponed_enabled": True},
    "processing": {"add_hashtags": False, "hashtags": []},
    "ollama": {"enabled": False, "url": "http://localhost:11434", "model": "llama3.2:3b", "target_words_min": 50, "target_words_max": 80},
    "filters": {"enable_auto_filters": False, "block_keywords": [], "block_hashtags": [], "min_content_length": 0}
}

with open("config.json", "w", encoding="utf-8") as f:
    json.dump(template, f, ensure_ascii=False, indent=2)

print("  [OK] config.json очищен от личных данных")
