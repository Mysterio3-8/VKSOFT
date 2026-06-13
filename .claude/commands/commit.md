---
description: Закоммитить текущие изменения с осмысленным сообщением
---

# /commit

Создаёт git-коммит для текущих изменений в `vk-post-reposting-bot/`.

## Шаги

1. Проверить состояние:
   ```bash
   git status --short
   git diff --stat
   ```

2. Если изменений нет — сообщить и остановиться.

3. Прочитать `git diff` (staged + unstaged) и `git log --oneline -5`,
   чтобы понять характер изменений и стиль сообщений в этом репо.

4. Составить commit message в формате `type: описание` (conventional commits:
   feat, fix, refactor, docs, test, chore, perf, tune, ci). Фокус на "почему",
   а не "что" — само сообщение короткое (1-2 строки).

5. Не коммитить:
   - `config.json` если в нём токены/секреты изменились вручную (спросить
     пользователя)
   - временные файлы, `__pycache__`, `*.pyc`

6. Добавить конкретные файлы по именам (не `git add -A`), создать коммит:
   ```bash
   git add <файлы>
   git commit -m "$(cat <<'EOF'
   type: описание

   Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
   EOF
   )"
   ```

7. Показать `git log --oneline -1` для подтверждения.

## Примечание

Хук post-commit в этом репо может автоматически обновить checkpoint в
CLAUDE.md и создать второй коммит — это ожидаемо, ничего не откатывать.

Пуш в remote — отдельным шагом, только если пользователь явно попросит.
