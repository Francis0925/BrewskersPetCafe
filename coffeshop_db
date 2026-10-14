CREATE DATABASE IF NOT EXISTS petcoffeeshop_db;
USE petcoffeeshop_db;
    
CREATE TABLE users (
    user_id         INT AUTO_INCREMENT PRIMARY KEY,
    username        VARCHAR(100) NOT NULL,
    email           VARCHAR(150) NOT NULL UNIQUE,
    password        VARCHAR(255) NOT NULL,
    role            VARCHAR(20) DEFAULT 'admin',
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE sessions (
    session_id  INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    token       VARCHAR(255) NOT NULL UNIQUE,
    expires_at  DATETIME NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE remember_tokens (
    token_id    INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    token       VARCHAR(255) NOT NULL UNIQUE,
    expires_at  DATETIME NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE otps (
    otp_id      INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    otp_code    VARCHAR(10) NOT NULL,
    purpose     VARCHAR(50) NOT NULL,
    expires_at  DATETIME NOT NULL,
    used_at     DATETIME DEFAULT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE store_profile (
    store_id    INT AUTO_INCREMENT PRIMARY KEY,
    store_name  VARCHAR(100) NOT NULL,
    address     VARCHAR(255),
    phone       VARCHAR(20),
    email       VARCHAR(150)
);
    
CREATE TABLE products (
    product_id  INT AUTO_INCREMENT PRIMARY KEY,
    category    VARCHAR(50) NOT NULL,
    name        VARCHAR(100) NOT NULL,
    price       DECIMAL(10,2) NOT NULL,
    stock       INT NOT NULL DEFAULT 0,
    status      VARCHAR(20) DEFAULT 'available'
);

CREATE TABLE orders (
    order_id        INT AUTO_INCREMENT PRIMARY KEY,
    order_no        VARCHAR(20) NOT NULL UNIQUE,
    customer_name   VARCHAR(100),
    total_amount    DECIMAL(10,2) NOT NULL,
    payment_method  VARCHAR(20) DEFAULT 'cash',
    amount_paid     DECIMAL(10,2),
    change_amount   DECIMAL(10,2),
    order_date      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE order_items (
    item_id     INT AUTO_INCREMENT PRIMARY KEY,
    order_id    INT NOT NULL,
    product_id  INT NOT NULL,
    quantity    INT NOT NULL,
    price       DECIMAL(10,2) NOT NULL,
    FOREIGN KEY (order_id)   REFERENCES orders(order_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE TABLE services (
    service_id  INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    price       DECIMAL(10,2) NOT NULL,
    duration    INT DEFAULT 30
);

CREATE TABLE appointments (
    appointment_id  INT AUTO_INCREMENT PRIMARY KEY,
    pet_name        VARCHAR(50) NOT NULL,
    owner_name      VARCHAR(100) NOT NULL,
    phone           VARCHAR(20) NOT NULL,
    service_id      INT NOT NULL,
    appt_date       DATE NOT NULL,
    appt_time       TIME NOT NULL,
    status          VARCHAR(20) DEFAULT 'scheduled',
    notes           TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (service_id) REFERENCES services(service_id)
);

-- Placeholders for inserts
INSERT INTO store_profile (store_name, address, phone, email) VALUES
('[store_name]', '[address]', '[phone_number]', '[email_address]');

INSERT INTO products (category, name, price, stock) VALUES
('[category]', '[product_name]', 0.00, 0);

INSERT INTO services (name, price, duration) VALUES
('[service_name]', 0.00, 0);