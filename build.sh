#!/bin/bash
# VK Post Bot — Build script (Linux/macOS)
set -e

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${GREEN}[*]${NC} $1"; }
warn()    { echo -e "${YELLOW}[!]${NC} $1"; }
error()   { echo -e "${RED}[✗]${NC} $1"; exit 1; }

echo ""
echo "  ============================================"
echo "   VK Post Bot — Сборка бинарного файла"
echo "  ============================================"
echo ""

# Check python3
command -v python3 >/dev/null 2>&1 || error "Python3 не найден. Установи: sudo apt install python3 python3-pip"

# Install deps
info "Устанавливаю зависимости..."
pip3 install pyinstaller --quiet --upgrade
pip3 install -r requirements.txt --quiet

# Clean config (no personal tokens)
info "Создаю чистый config.json..."
python3 -c "
import json
template = {
    'vk': {'user_token': '', 'group_token': '', 'group_id': '', 'api_version': '5.131'},
    'sources': [],
    'download_settings': {'posts_to_download': 100, 'batch_size': 100, 'delay_between_requests': 1, 'check_duplicates': True},
    'publishing_settings': {'posts_to_publish': 50, 'publish_delay': 3600, 'postponed_enabled': True},
    'processing': {'add_hashtags': False, 'hashtags': []},
    'ollama': {'enabled': False, 'url': 'http://localhost:11434', 'model': 'llama3.2:3b', 'target_words_min': 50, 'target_words_max': 80},
    'filters': {'enable_auto_filters': False, 'block_keywords': [], 'block_hashtags': [], 'min_content_length': 0}
}
with open('config.json', 'w', encoding='utf-8') as f:
    json.dump(template, f, ensure_ascii=False, indent=2)
print('  config.json очищен')
"

# Build
info "Собираю бинарник (1-3 минуты)..."
pyinstaller \
    --noconfirm \
    --onefile \
    --name "vk_post_bot" \
    --add-data "frontend:frontend" \
    --add-data "config.json:." \
    --hidden-import "uvicorn.logging" \
    --hidden-import "uvicorn.loops" \
    --hidden-import "uvicorn.loops.auto" \
    --hidden-import "uvicorn.protocols" \
    --hidden-import "uvicorn.protocols.http" \
    --hidden-import "uvicorn.protocols.http.auto" \
    --hidden-import "uvicorn.protocols.websockets" \
    --hidden-import "uvicorn.protocols.websockets.auto" \
    --hidden-import "uvicorn.lifespan" \
    --hidden-import "uvicorn.lifespan.on" \
    --hidden-import "vk_api" \
    --hidden-import "fastapi" \
    --hidden-import "starlette" \
    --hidden-import "anyio" \
    main.py

if [ -f "dist/vk_post_bot" ]; then
    cp README_USER.txt dist/README_USER.txt 2>/dev/null || true
    chmod +x dist/vk_post_bot
    echo ""
    echo -e "${GREEN}  ============================================${NC}"
    echo -e "${GREEN}  Готово! Файл: dist/vk_post_bot${NC}"
    echo -e "${GREEN}  ============================================${NC}"
    echo ""
    echo "  Передай папку dist/ человеку."
    echo "  Запуск: ./vk_post_bot"
    echo ""
else
    error "Файл не был создан. Смотри лог выше."
fi
