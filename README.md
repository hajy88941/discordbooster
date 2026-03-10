# Discord Boost Checker

Массовая проверка Discord-аккаунтов на наличие активных Nitro Boost подписок.

## Установка

```bash
pip install -r requirements.txt
cp .env.example .env   # настроить параметры
```

## Использование

### 1. Импорт данных

```bash
# Токены — один на строку
python main.py import-tokens tokens.txt

# Прокси — формат protocol://user:pass@host:port, один на строку
python main.py import-proxies proxies.txt
```

### 2. Запуск проверки

```bash
python main.py run
```

Прогресс пишется в лог каждые 30 секунд. Можно прервать по `Ctrl+C` — при следующем запуске проверка продолжится с того же места.

### 3. Просмотр статистики

```bash
python main.py stats
```

### 4. Экспорт аккаунтов с бустами

```bash
python main.py export boosted.txt
```

Формат: `token|boost_count|premium_type|guilds_json`

### 5. Сброс

```bash
python main.py reset
```

## Конфигурация (.env)

| Параметр | По умолчанию | Описание |
|---|---|---|
| `MAX_WORKERS` | 100 | Параллельных воркеров |
| `MAX_PER_PROXY` | 3 | Макс. одновременных запросов через 1 прокси |
| `BATCH_SIZE` | 500 | Размер батча из БД |
| `REQUEST_TIMEOUT` | 15 | Таймаут запроса (сек) |
| `MAX_RETRIES` | 3 | Попыток на аккаунт |
| `MIN_DELAY` / `MAX_DELAY` | 0.5 / 2.0 | Jitter между запросами (сек) |
| `CAPTCHA_API_KEY` | — | Ключ 2captcha (если пусто — капча не решается) |
| `PROXY_MAX_FAILS` | 5 | Макс. ошибок до отключения прокси |
| `PROXY_BLOCK_DURATION` | 300 | Блокировка прокси после 403 (сек) |

## Статусы аккаунтов

| Статус | Значение |
|---|---|
| `pending` | Ожидает проверки |
| `processing` | Сейчас обрабатывается |
| `ok` | Токен валиден, проверка завершена |
| `invalid_token` | Токен недействителен (401) |
| `banned` | Аккаунт забанен (403 без капчи) |
| `captcha_failed` | Не удалось решить капчу |
| `error` | Временная ошибка (будет повторена) |
