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
    emoji       VARCHAR(10) DEFAULT '☕',
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
    pet_type        VARCHAR(10) DEFAULT 'Dog',
    breed           VARCHAR(50),
    pet_age         VARCHAR(30),
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

-- Sample data (edit freely)
INSERT INTO store_profile (store_name, address, phone, email) VALUES
('Whisker & Brew', '123 Sample St', '0900-000-0000', 'hello@whiskerbrew.example');
INSERT INTO products (category, name, price, stock, emoji) VALUES
('Coffee', 'Paw Print Latte', 150.00, 24, '☕'), ('Coffee', 'Honey Oat Cappuccino', 145.00, 18, '🥛'),
('Coffee', 'Cold Brew', 130.00, 12, '🧊'), ('Treats', 'Blueberry Pupcake', 105.00, 8, '🧁'),
('Pet Treats', 'Peanut Butter Biscuit', 70.00, 4, '🦴'), ('Pet Treats', 'Salmon Kitty Bites', 90.00, 15, '🐟'),
('Kitchen', 'Avocado Toast', 210.00, 11, '🥑'), ('Treats', 'Cinnamon Roll', 120.00, 4, '🥐');
INSERT INTO services (name, price, duration) VALUES
('Pup playdate', 350.00, 60), ('Cat lounge visit', 250.00, 45), ('Birthday paw-ty', 2500.00, 120);
INSERT INTO appointments (pet_name, pet_type, breed, pet_age, owner_name, phone, service_id, appt_date, appt_time, notes) VALUES
('Mochi','Dog','Cavapoo','2 years','Lena Park','0900-111-1111',1,CURDATE(),'09:30','Friendly and curious. Loves peanut butter biscuits.'),
('Oliver','Cat','Tuxedo','4 years','Ken Ito','0900-222-2222',2,CURDATE(),'11:00','Shy at first.'),
('Waffles','Dog','Corgi','3 years','Nico Reyes','0900-333-3333',3,CURDATE(),'14:30','Birthday cake is nut-free.'),
('Luna','Cat','Calico','18 months','Ana Cruz','0900-444-4444',2,DATE_ADD(CURDATE(),INTERVAL 1 DAY),'10:15','');
