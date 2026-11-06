CREATE DATABASE IF NOT EXISTS machineDb;
USE machineDb;

CREATE TABLE machines (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    alias VARCHAR(255) NOT NULL,
    location VARCHAR(512) NOT NULL
);

CREATE TABLE drinks (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    machine_id INT UNSIGNED NOT NULL,
    name VARCHAR(255) NOT NULL,
    image VARCHAR(255),
    description VARCHAR(512),
    price DECIMAL(10,2) NOT NULL,
    available BOOLEAN DEFAULT TRUE,
    UNIQUE (machine_id, name),
    FOREIGN KEY (machine_id) REFERENCES machines(id) ON DELETE CASCADE
);

CREATE TABLE ingredients (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    machine_id INT UNSIGNED NOT NULL,
    name VARCHAR(255) NOT NULL,
    stock DECIMAL(10,2) NOT NULL DEFAULT 0,
    UNIQUE (machine_id, name),
    FOREIGN KEY (machine_id) REFERENCES machines(id) ON DELETE CASCADE
);

CREATE TABLE recipes (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    machine_id INT UNSIGNED NOT NULL,
    drink_id INT UNSIGNED NOT NULL,
    ingredient_id INT UNSIGNED NOT NULL,
    step_index INT NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    FOREIGN KEY (machine_id) REFERENCES machines(id) ON DELETE CASCADE,
    FOREIGN KEY (drink_id) REFERENCES drinks(id) ON DELETE CASCADE,
    FOREIGN KEY (ingredient_id) REFERENCES ingredients(id) ON DELETE CASCADE,
    UNIQUE (machine_id, drink_id, step_index) -- Виправлено унікальність
);

-- Додаємо автомати
INSERT INTO machines (id, alias, location) VALUES
(55131, 'Офіс 1', 'Київ, вул. Хрещатик, 1'),
(55132, 'ТРЦ', 'Львів, вул. Дорошенка, 15');

-- Додаємо напої
INSERT INTO drinks (machine_id, name, image, description, price, available) VALUES
(55131, 'Кава', 'coffee.jpg', 'Міцна чорна кава', 15.00, TRUE),
(55131, 'Чай', 'tea.jpg', 'Ароматний чорний чай', 10.00, TRUE);

-- Додаємо інгредієнти
INSERT INTO ingredients (machine_id, name, stock) VALUES
(55131, 'Стакан', 100),
(55131, 'Вода', 5000),
(55131, 'Цукор', 1000),
(55131, 'Молоко', 2000),
(55131, 'Чай', 800);

-- Додаємо рецепти
INSERT INTO recipes (machine_id, drink_id, ingredient_id, step_index, amount) VALUES
(55131, 1, 1, 1, 1),   -- Кава - Стакан - 1
(55131, 1, 2, 2, 100), -- Кава - Вода - 100
(55131, 1, 3, 3, 5),   -- Кава - Цукор - 5
(55131, 1, 4, 4, 10),  -- Кава - Молоко - 10
(55131, 2, 1, 1, 1),   -- Чай - Стакан - 1
(55131, 2, 2, 2, 100), -- Чай - Вода - 100
(55131, 2, 3, 3, 5),   -- Чай - Цукор - 5
(55131, 2, 5, 4, 10);  -- Чай - Чай - 10
