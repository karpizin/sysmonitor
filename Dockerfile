FROM python:3.12-slim

# Установка необходимых системных пакетов
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    procps \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Создание рабочей директории
WORKDIR /app

# Копирование requirements.txt и установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование исходного кода
COPY system_monitor.py .

# Запуск приложения
CMD ["python", "system_monitor.py"]
