#!/bin/bash
# ============================================================
#  VK Post Bot — Setup Script for Aeza VPS (Ubuntu)
#  Run as root: bash setup_aeza.sh
# ============================================================

set -e

BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${BLUE}[*]${NC} $1"; }
success() { echo -e "${GREEN}[✓]${NC} $1"; }
warn()    { echo -e "${YELLOW}[!]${NC} $1"; }
error()   { echo -e "${RED}[✗]${NC} $1"; exit 1; }

BOT_DIR="/opt/vk-bot"
BOT_USER="vkbot"

echo -e "${BLUE}"
echo "  ============================================"
echo "   VK Post Bot — Auto Setup"
echo "  ============================================"
echo -e "${NC}"

# ============================================================
# 1. System update
# ============================================================
info "Обновляю систему..."
apt-get update -qq && apt-get upgrade -y -qq
apt-get install -y -qq python3 python3-pip python3-venv curl wget git screen
success "Система обновлена"

# ============================================================
# 2. Create bot user
# ============================================================
if ! id "$BOT_USER" &>/dev/null; then
    info "Создаю пользователя $BOT_USER..."
    useradd -m -s /bin/bash "$BOT_USER"
    success "Пользователь создан"
else
    warn "Пользователь $BOT_USER уже существует"
fi

# ============================================================
# 3. Copy bot files
# ============================================================
info "Копирую файлы бота в $BOT_DIR..."
mkdir -p "$BOT_DIR"
cp -r . "$BOT_DIR/"
chown -R "$BOT_USER:$BOT_USER" "$BOT_DIR"
success "Файлы скопированы"

# ============================================================
# 4. Python venv + dependencies
# ============================================================
info "Настраиваю Python окружение..."
sudo -u "$BOT_USER" bash -c "
    cd $BOT_DIR
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip -q
    pip install -r requirements.txt -q
"
success "Python зависимости установлены"

# ============================================================
# 5. Systemd service for VK Bot
# ============================================================
info "Создаю systemd сервис vk-bot..."
cat > /etc/systemd/system/vk-bot.service << EOF
[Unit]
Description=VK Post Reposting Bot
After=network.target

[Service]
Type=simple
User=$BOT_USER
WorkingDirectory=$BOT_DIR
ExecStart=$BOT_DIR/venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONIOENCODING=utf-8

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable vk-bot
systemctl start vk-bot
success "Сервис vk-bot запущен"

# ============================================================
# 6. Configure firewall (ufw)
# ============================================================
if command -v ufw &>/dev/null; then
    info "Настраиваю фаервол..."
    ufw allow ssh
    ufw allow 8000/tcp  # VK Bot web UI
    ufw --force enable
    success "Фаервол настроен (порт 8000 открыт)"
else
    warn "ufw не найден, открой порт 8000 вручную"
fi

# ============================================================
# 7. Summary
# ============================================================
SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Установка завершена!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "  Веб-интерфейс бота:  ${YELLOW}http://$SERVER_IP:8000${NC}"
echo ""
echo -e "  Управление сервисом:"
echo -e "    systemctl status vk-bot      — статус"
echo -e "    systemctl restart vk-bot     — перезапуск"
echo -e "    journalctl -u vk-bot -f      — логи в реальном времени"
echo ""
echo -e "  Файлы бота:  ${YELLOW}$BOT_DIR${NC}"
echo -e "  Конфиг:      ${YELLOW}$BOT_DIR/config.json${NC}"
echo ""
