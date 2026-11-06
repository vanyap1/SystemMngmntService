#!/bin/bash

# Конфігурація бази даних
USER="vanya"
PASSWORD="1234"
DATABASE="machineDb"
BACKUP_DIR="sql"

# Перевірка аргументів
if [ "$#" -ne 1 ]; then
    echo "Використання: $0 [backup|restore]"
    exit 1
fi

# Аргумент дії
ACTION=$1

# Створення папки для бекапів, якщо вона не існує
mkdir -p "$BACKUP_DIR"

# Функція для створення бекапів
backup_tables() {
    echo "Створення бекапу для бази даних '$DATABASE'..."

    # Список таблиць для бекапу
    TABLES=("ingredients" "users" "user_levels" "recipes" "machines" "drinks")

    # Створення бекапів для кожної таблиці
    for TABLE in "${TABLES[@]}"; do
        echo "Бекап таблиці: $TABLE"
        mysqldump -u "$USER" -p"$PASSWORD" "$DATABASE" "$TABLE" > "$BACKUP_DIR/$TABLE.sql"
        if [ $? -eq 0 ]; then
            echo "Таблиця $TABLE успішно збережена."
        else
            echo "Помилка при збереженні таблиці $TABLE."
        fi
    done

    echo "Бекапи збережено в папці '$BACKUP_DIR'."
}

# Функція для відновлення таблиць
restore_tables() {
    echo "Відновлення таблиць у базу даних '$DATABASE'..."

    # Список таблиць для відновлення
    TABLES=("ingredients" "users" "user_levels" "recipes" "machines" "drinks")

    # Відновлення таблиць із SQL-файлів
    for TABLE in "${TABLES[@]}"; do
        FILE="$BACKUP_DIR/$TABLE.sql"
        if [ -f "$FILE" ]; then
            echo "Відновлення таблиці: $TABLE"
            mysql -u "$USER" -p"$PASSWORD" "$DATABASE" < "$FILE"
            if [ $? -eq 0 ]; then
                echo "Таблиця $TABLE успішно відновлена."
            else
                echo "Помилка при відновленні таблиці $TABLE."
            fi
        else
            echo "Файл для таблиці $TABLE не знайдено: $FILE"
        fi
    done

    echo "Відновлення завершено."
}

# Виконання дій залежно від аргументу
case $ACTION in
    backup)
        backup_tables
        ;;
    restore)
        restore_tables
        ;;
    *)
        echo "Невідома дія: $ACTION. Використовуйте 'backup' або 'restore'."
        exit 1
        ;;
esac