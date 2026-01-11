-- ============================================
-- M_Tracker Database Schema
-- MySQL Implementation
-- Version: 1.0
-- Created: December 2025
-- ============================================

-- Create Database
CREATE DATABASE IF NOT EXISTS m_tracker
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE m_tracker;
-- ============================================
-- USERS TABLE
-- Stores user authentication and profile info
-- ============================================
CREATE TABLE users (
    id VARCHAR(50) PRIMARY KEY COMMENT 'Unique user ID (e.g., 1763904760.105118)',
    name VARCHAR(100) NOT NULL COMMENT 'Full name of the user',
    username VARCHAR(50) NOT NULL UNIQUE COMMENT 'Login username (e.g., phone number)',
    password_hash VARCHAR(255) NOT NULL COMMENT 'Hashed password (pbkdf2:sha256)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,

    INDEX idx_username (username)
) ENGINE=InnoDB COMMENT='User accounts and authentication';

-- ============================================
-- ACCOUNTS TABLE
-- Financial accounts (Cash, Bank accounts, etc.)
-- ============================================
CREATE TABLE accounts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    account_name VARCHAR(50) NOT NULL COMMENT 'Account name (e.g., Cash, SBI-1, ALHB)',
    account_type ENUM('cash', 'bank', 'wallet', 'credit_card', 'other') DEFAULT 'bank',
    is_active BOOLEAN DEFAULT TRUE,
    display_order INT DEFAULT 0 COMMENT 'Order for display in dropdowns',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uk_user_account (user_id, account_name),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id)
) ENGINE=InnoDB COMMENT='Financial accounts per user';

-- ============================================
-- CATEGORIES TABLE
-- Expense/Income categories
-- ============================================
CREATE TABLE categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    category_name VARCHAR(50) NOT NULL COMMENT 'Category name (e.g., Bills, Food, EMI)',
    category_type ENUM('expense', 'income', 'both') DEFAULT 'expense',
    color VARCHAR(7) DEFAULT NULL COMMENT 'Hex color code for UI',
    icon VARCHAR(50) DEFAULT NULL COMMENT 'Icon name for UI',
    is_active BOOLEAN DEFAULT TRUE,
    display_order INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uk_user_category (user_id, category_name),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id)
) ENGINE=InnoDB COMMENT='Expense and income categories';

-- ============================================
-- MONTHS TABLE
-- Monthly financial periods
-- ============================================
CREATE TABLE months (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    month_key VARCHAR(7) NOT NULL COMMENT 'Month identifier (e.g., 2025-11)',
    year INT NOT NULL,
    month INT NOT NULL COMMENT 'Month number (1-12)',
    is_closed BOOLEAN DEFAULT FALSE COMMENT 'Whether month is finalized',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_user_month (user_id, month_key),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id),
    INDEX idx_year_month (year, month)
) ENGINE=InnoDB COMMENT='Monthly financial periods';

-- ============================================
-- OPENING BALANCES TABLE
-- Opening balance per account per month
-- ============================================
CREATE TABLE opening_balances (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    month_id INT NOT NULL,
    account_id INT NOT NULL,
    amount DECIMAL(15, 2) NOT NULL DEFAULT 0.00,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_month_account (month_id, account_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (month_id) REFERENCES months(id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id),
    INDEX idx_month_id (month_id)
) ENGINE=InnoDB COMMENT='Opening balances per account per month';

-- ============================================
-- INCOME TABLE
-- Income entries
-- ============================================
CREATE TABLE income (
    id VARCHAR(100) PRIMARY KEY COMMENT 'Unique ID (timestamp-based from JSON)',
    user_id VARCHAR(50) NOT NULL,
    month_id INT NOT NULL,
    account_id INT NOT NULL,
    source VARCHAR(100) NOT NULL COMMENT 'Income source (e.g., Salary, Reimbursement)',
    amount DECIMAL(15, 2) NOT NULL,
    income_date DATE DEFAULT NULL,
    notes TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (month_id) REFERENCES months(id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE RESTRICT,
    INDEX idx_user_id (user_id),
    INDEX idx_month_id (month_id),
    INDEX idx_account_id (account_id),
    INDEX idx_income_date (income_date)
) ENGINE=InnoDB COMMENT='Income entries';

-- ============================================
-- PAID EXPENSES TABLE
-- Completed/Paid expense entries
-- ============================================
CREATE TABLE paid_expenses (
    id VARCHAR(100) PRIMARY KEY COMMENT 'Unique ID (timestamp-based from JSON)',
    user_id VARCHAR(50) NOT NULL,
    month_id INT NOT NULL,
    account_id INT NULL COMMENT 'Account ID (Nullable for some long-pending partial payments)',
    category_id INT NOT NULL,
    reason VARCHAR(255) NOT NULL COMMENT 'Expense description/reason',
    amount DECIMAL(15, 2) NOT NULL,
    expense_date DATE NOT NULL,
    is_long_pending BOOLEAN DEFAULT FALSE COMMENT 'Whether this came from long pending',
    linked_long_pending_id VARCHAR(100) DEFAULT NULL COMMENT 'Reference to long_pending if applicable',
    notes TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (month_id) REFERENCES months(id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE SET NULL,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE RESTRICT,
    INDEX idx_user_id (user_id),
    INDEX idx_month_id (month_id),
    INDEX idx_account_id (account_id),
    INDEX idx_category_id (category_id),
    INDEX idx_expense_date (expense_date),
    INDEX idx_is_long_pending (is_long_pending)
) ENGINE=InnoDB COMMENT='Paid/completed expense entries';

-- ============================================
-- PERSONAL/DAILY EXPENSES TABLE
-- Daily personal expense entries
-- ============================================
CREATE TABLE personal_expenses (
    id VARCHAR(100) PRIMARY KEY COMMENT 'Unique ID (timestamp-based from JSON)',
    user_id VARCHAR(50) NOT NULL,
    month_id INT NOT NULL,
    account_id INT NOT NULL,
    reason VARCHAR(255) NOT NULL COMMENT 'Expense item (e.g., Rapido, Grocery)',
    amount DECIMAL(15, 2) NOT NULL,
    expense_date DATE NOT NULL,
    notes TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (month_id) REFERENCES months(id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE RESTRICT,
    INDEX idx_user_id (user_id),
    INDEX idx_month_id (month_id),
    INDEX idx_account_id (account_id),
    INDEX idx_expense_date (expense_date)
) ENGINE=InnoDB COMMENT='Personal/daily expense entries';

-- ============================================
-- PENDING EXPENSES TABLE
-- Pending/Budget expense entries (not yet paid)
-- ============================================
CREATE TABLE pending_expenses (
    id VARCHAR(100) PRIMARY KEY COMMENT 'Unique ID (timestamp-based from JSON)',
    user_id VARCHAR(50) NOT NULL,
    month_id INT NOT NULL,
    category_id INT NOT NULL,
    reason VARCHAR(255) NOT NULL COMMENT 'Pending expense description',
    amount DECIMAL(15, 2) NOT NULL,
    payment_mode ENUM('online', 'cash', 'cheque', 'other') DEFAULT 'online',
    due_date DATE DEFAULT NULL,
    status ENUM('pending', 'paid', 'cancelled') DEFAULT 'pending',
    paid_date DATE DEFAULT NULL COMMENT 'Date when marked as paid',
    paid_expense_id VARCHAR(100) DEFAULT NULL COMMENT 'Reference to paid_expenses when paid',
    notes TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (month_id) REFERENCES months(id) ON DELETE CASCADE,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE RESTRICT,
    INDEX idx_user_id (user_id),
    INDEX idx_month_id (month_id),
    INDEX idx_category_id (category_id),
    INDEX idx_status (status)
) ENGINE=InnoDB COMMENT='Pending/budget expense entries';

-- ============================================
-- LONG PENDING PAYMENTS TABLE
-- Long-term pending payments (loans, dues, etc.)
-- ============================================
CREATE TABLE long_pending (
    id VARCHAR(100) PRIMARY KEY COMMENT 'Unique ID (timestamp-based from JSON)',
    user_id VARCHAR(50) NOT NULL,
    reason VARCHAR(255) NOT NULL COMMENT 'Description (e.g., person name, loan purpose)',
    total_amount DECIMAL(15, 2) NOT NULL COMMENT 'Total amount to be paid',
    paid_amount DECIMAL(15, 2) NOT NULL DEFAULT 0.00 COMMENT 'Amount paid so far',
    remaining_amount DECIMAL(15, 2) GENERATED ALWAYS AS (total_amount - paid_amount) STORED,
    category VARCHAR(50) DEFAULT 'General',
    status ENUM('active', 'completed', 'cancelled') DEFAULT 'active',
    created_date DATE NOT NULL,
    completed_date DATE DEFAULT NULL,
    notes TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id),
    INDEX idx_status (status),
    INDEX idx_created_date (created_date)
) ENGINE=InnoDB COMMENT='Long-term pending payments (loans, dues)';

-- ============================================
-- LONG PENDING PAYMENTS HISTORY TABLE
-- Tracks partial payments made towards long pending items
-- ============================================
CREATE TABLE long_pending_payments (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    long_pending_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(50) NOT NULL,
    month_id INT NOT NULL COMMENT 'Month in which payment was made',
    account_id INT NOT NULL,
    amount DECIMAL(15, 2) NOT NULL COMMENT 'Payment amount',
    payment_mode ENUM('online', 'cash', 'cheque', 'other') DEFAULT 'online',
    payment_date DATE NOT NULL,
    linked_expense_id VARCHAR(100) DEFAULT NULL COMMENT 'Reference to paid_expenses entry',
    notes TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (long_pending_id) REFERENCES long_pending(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (month_id) REFERENCES months(id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE RESTRICT,
    INDEX idx_long_pending_id (long_pending_id),
    INDEX idx_user_id (user_id),
    INDEX idx_month_id (month_id),
    INDEX idx_payment_date (payment_date)
) ENGINE=InnoDB COMMENT='Payment history for long pending items';

-- ============================================
-- NOTES TABLE
-- User notes per month
-- ============================================
CREATE TABLE notes (
    id VARCHAR(100) PRIMARY KEY COMMENT 'Unique ID (timestamp-based from JSON)',
    user_id VARCHAR(50) NOT NULL,
    month_id INT NOT NULL,
    title VARCHAR(255) NOT NULL,
    content TEXT DEFAULT NULL,
    note_date DATE NOT NULL,
    updated_date DATE DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (month_id) REFERENCES months(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id),
    INDEX idx_month_id (month_id),
    INDEX idx_note_date (note_date)
) ENGINE=InnoDB COMMENT='User notes per month';

-- ============================================
-- USER SETTINGS TABLE
-- User preferences and settings
-- ============================================
CREATE TABLE user_settings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL UNIQUE,
    currency VARCHAR(10) DEFAULT 'INR',
    currency_symbol VARCHAR(5) DEFAULT '₹',
    date_format VARCHAR(20) DEFAULT 'YYYY-MM-DD',
    theme ENUM('dark', 'light', 'auto') DEFAULT 'dark',
    default_account_id INT DEFAULT NULL,
    notifications_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (default_account_id) REFERENCES accounts(id) ON DELETE SET NULL
) ENGINE=InnoDB COMMENT='User preferences and settings';

-- ============================================
-- AUDIT LOG TABLE (Optional - for tracking changes)
-- ============================================
CREATE TABLE audit_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    table_name VARCHAR(50) NOT NULL,
    record_id VARCHAR(100) NOT NULL,
    action ENUM('INSERT', 'UPDATE', 'DELETE') NOT NULL,
    old_values JSON DEFAULT NULL,
    new_values JSON DEFAULT NULL,
    ip_address VARCHAR(45) DEFAULT NULL,
    user_agent VARCHAR(255) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_user_id (user_id),
    INDEX idx_table_name (table_name),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB COMMENT='Audit trail for data changes';

-- ============================================
-- VIEWS
-- ============================================

-- Monthly Summary View
CREATE OR REPLACE VIEW v_monthly_summary AS
SELECT
    m.id AS month_id,
    m.user_id,
    m.month_key,
    m.year,
    m.month,
    COALESCE(ob.total_opening, 0) AS total_opening_balance,
    COALESCE(inc.total_income, 0) AS total_income,
    COALESCE(pe.total_paid, 0) AS total_paid_expenses,
    COALESCE(pers.total_personal, 0) AS total_personal_expenses,
    COALESCE(pend.total_pending, 0) AS total_pending_expenses,
    (COALESCE(ob.total_opening, 0) + COALESCE(inc.total_income, 0)) AS initial_balance,
    (COALESCE(ob.total_opening, 0) + COALESCE(inc.total_income, 0) - COALESCE(pe.total_paid, 0) - COALESCE(pers.total_personal, 0)) AS current_balance,
    (COALESCE(ob.total_opening, 0) + COALESCE(inc.total_income, 0) - COALESCE(pe.total_paid, 0) - COALESCE(pers.total_personal, 0) - COALESCE(pend.total_pending, 0)) AS expected_balance
FROM months m
LEFT JOIN (
    SELECT month_id, SUM(amount) AS total_opening
    FROM opening_balances GROUP BY month_id
) ob ON m.id = ob.month_id
LEFT JOIN (
    SELECT month_id, SUM(amount) AS total_income
    FROM income GROUP BY month_id
) inc ON m.id = inc.month_id
LEFT JOIN (
    SELECT month_id, SUM(amount) AS total_paid
    FROM paid_expenses GROUP BY month_id
) pe ON m.id = pe.month_id
LEFT JOIN (
    SELECT month_id, SUM(amount) AS total_personal
    FROM personal_expenses GROUP BY month_id
) pers ON m.id = pers.month_id
LEFT JOIN (
    SELECT month_id, SUM(amount) AS total_pending
    FROM pending_expenses WHERE status = 'pending' GROUP BY month_id
) pend ON m.id = pend.month_id;

-- Account Balance View
CREATE OR REPLACE VIEW v_account_balances AS
SELECT
    a.id AS account_id,
    a.user_id,
    a.account_name,
    m.id AS month_id,
    m.month_key,
    COALESCE(ob.amount, 0) AS opening_balance,
    COALESCE(inc.total_income, 0) AS income,
    COALESCE(pe.total_paid, 0) AS paid_expenses,
    COALESCE(pers.total_personal, 0) AS personal_expenses,
    (COALESCE(ob.amount, 0) + COALESCE(inc.total_income, 0)) AS initial_balance,
    (COALESCE(ob.amount, 0) + COALESCE(inc.total_income, 0) - COALESCE(pe.total_paid, 0) - COALESCE(pers.total_personal, 0)) AS current_balance
FROM accounts a
CROSS JOIN months m
LEFT JOIN opening_balances ob ON a.id = ob.account_id AND m.id = ob.month_id
LEFT JOIN (
    SELECT month_id, account_id, SUM(amount) AS total_income
    FROM income GROUP BY month_id, account_id
) inc ON m.id = inc.month_id AND a.id = inc.account_id
LEFT JOIN (
    SELECT month_id, account_id, SUM(amount) AS total_paid
    FROM paid_expenses GROUP BY month_id, account_id
) pe ON m.id = pe.month_id AND a.id = pe.account_id
LEFT JOIN (
    SELECT month_id, account_id, SUM(amount) AS total_personal
    FROM personal_expenses GROUP BY month_id, account_id
) pers ON m.id = pers.month_id AND a.id = pers.account_id
WHERE a.user_id = m.user_id;

-- Category-wise Expense Summary View
CREATE OR REPLACE VIEW v_category_expenses AS
SELECT
    c.id AS category_id,
    c.user_id,
    c.category_name,
    m.id AS month_id,
    m.month_key,
    COALESCE(pe.total_amount, 0) AS total_amount,
    COALESCE(pe.expense_count, 0) AS expense_count
FROM categories c
CROSS JOIN months m
LEFT JOIN (
    SELECT month_id, category_id, SUM(amount) AS total_amount, COUNT(*) AS expense_count
    FROM paid_expenses GROUP BY month_id, category_id
) pe ON m.id = pe.month_id AND c.id = pe.category_id
WHERE c.user_id = m.user_id;

-- Long Pending Summary View
CREATE OR REPLACE VIEW v_long_pending_summary AS
SELECT
    lp.id,
    lp.user_id,
    lp.reason,
    lp.total_amount,
    lp.paid_amount,
    lp.remaining_amount,
    lp.status,
    lp.created_date,
    COUNT(lpp.id) AS payment_count,
    MAX(lpp.payment_date) AS last_payment_date
FROM long_pending lp
LEFT JOIN long_pending_payments lpp ON lp.id = lpp.long_pending_id
GROUP BY lp.id;

-- ============================================
-- STORED PROCEDURES
-- ============================================

DELIMITER //

-- Procedure to create a new month with optional pending carry-forward
CREATE PROCEDURE sp_create_month(
    IN p_user_id VARCHAR(50),
    IN p_month_key VARCHAR(7),
    IN p_copy_pending BOOLEAN
)
BEGIN
    DECLARE v_year INT;
    DECLARE v_month INT;
    DECLARE v_new_month_id INT;
    DECLARE v_prev_month_id INT;

    -- Extract year and month
    SET v_year = CAST(SUBSTRING(p_month_key, 1, 4) AS UNSIGNED);
    SET v_month = CAST(SUBSTRING(p_month_key, 6, 2) AS UNSIGNED);

    -- Insert new month
    INSERT INTO months (user_id, month_key, year, month)
    VALUES (p_user_id, p_month_key, v_year, v_month);

    SET v_new_month_id = LAST_INSERT_ID();

    -- Copy pending expenses if requested
    IF p_copy_pending THEN
        -- Find previous month
        SELECT id INTO v_prev_month_id
        FROM months
        WHERE user_id = p_user_id AND month_key < p_month_key
        ORDER BY month_key DESC
        LIMIT 1;

        IF v_prev_month_id IS NOT NULL THEN
            INSERT INTO pending_expenses (id, user_id, month_id, category_id, reason, amount, payment_mode, status)
            SELECT
                CONCAT(UNIX_TIMESTAMP(NOW(6)) * 1000, '-', FLOOR(RAND() * 1000)),
                user_id,
                v_new_month_id,
                category_id,
                reason,
                amount,
                payment_mode,
                'pending'
            FROM pending_expenses
            WHERE month_id = v_prev_month_id AND status = 'pending';
        END IF;
    END IF;

    SELECT v_new_month_id AS month_id;
END //

-- Procedure to pay a pending expense
CREATE PROCEDURE sp_pay_pending_expense(
    IN p_pending_id VARCHAR(100),
    IN p_account_id INT,
    IN p_payment_date DATE
)
BEGIN
    DECLARE v_user_id VARCHAR(50);
    DECLARE v_month_id INT;
    DECLARE v_category_id INT;
    DECLARE v_reason VARCHAR(255);
    DECLARE v_amount DECIMAL(15,2);
    DECLARE v_new_expense_id VARCHAR(100);

    -- Get pending expense details
    SELECT user_id, month_id, category_id, reason, amount
    INTO v_user_id, v_month_id, v_category_id, v_reason, v_amount
    FROM pending_expenses
    WHERE id = p_pending_id AND status = 'pending';

    IF v_user_id IS NOT NULL THEN
        -- Generate new ID
        SET v_new_expense_id = CAST(UNIX_TIMESTAMP(NOW(6)) * 1000 AS CHAR);

        -- Insert into paid expenses
        INSERT INTO paid_expenses (id, user_id, month_id, account_id, category_id, reason, amount, expense_date)
        VALUES (v_new_expense_id, v_user_id, v_month_id, p_account_id, v_category_id, v_reason, v_amount, p_payment_date);

        -- Update pending expense status
        UPDATE pending_expenses
        SET status = 'paid', paid_date = p_payment_date, paid_expense_id = v_new_expense_id
        WHERE id = p_pending_id;

        SELECT v_new_expense_id AS expense_id, 'success' AS status;
    ELSE
        SELECT NULL AS expense_id, 'not_found' AS status;
    END IF;
END //

-- Procedure to make partial payment on long pending
CREATE PROCEDURE sp_pay_long_pending(
    IN p_long_pending_id VARCHAR(100),
    IN p_user_id VARCHAR(50),
    IN p_month_id INT,
    IN p_account_id INT,
    IN p_amount DECIMAL(15,2),
    IN p_payment_mode VARCHAR(20),
    IN p_payment_date DATE
)
BEGIN
    DECLARE v_remaining DECIMAL(15,2);
    DECLARE v_reason VARCHAR(255);
    DECLARE v_new_expense_id VARCHAR(100);
    DECLARE v_lp_category_id INT;

    -- Get long pending details
    SELECT remaining_amount, reason INTO v_remaining, v_reason
    FROM long_pending
    WHERE id = p_long_pending_id AND user_id = p_user_id AND status = 'active';

    IF v_remaining IS NOT NULL AND p_amount <= v_remaining THEN
        -- Get or create "Long Pending" category
        SELECT id INTO v_lp_category_id
        FROM categories
        WHERE user_id = p_user_id AND category_name = 'Long Pending'
        LIMIT 1;

        IF v_lp_category_id IS NULL THEN
            INSERT INTO categories (user_id, category_name, category_type)
            VALUES (p_user_id, 'Long Pending', 'expense');
            SET v_lp_category_id = LAST_INSERT_ID();
        END IF;

        -- Generate new expense ID
        SET v_new_expense_id = CONCAT('lp-', p_long_pending_id, '-', UNIX_TIMESTAMP());

        -- Insert into paid expenses
        INSERT INTO paid_expenses (id, user_id, month_id, account_id, category_id, reason, amount, expense_date, is_long_pending, linked_long_pending_id)
        VALUES (v_new_expense_id, p_user_id, p_month_id, p_account_id, v_lp_category_id, CONCAT('Partial: ', v_reason), p_amount, p_payment_date, TRUE, p_long_pending_id);

        -- Record payment in history
        INSERT INTO long_pending_payments (long_pending_id, user_id, month_id, account_id, amount, payment_mode, payment_date, linked_expense_id)
        VALUES (p_long_pending_id, p_user_id, p_month_id, p_account_id, p_amount, p_payment_mode, p_payment_date, v_new_expense_id);

        -- Update long pending paid amount
        UPDATE long_pending
        SET paid_amount = paid_amount + p_amount,
            status = IF(paid_amount + p_amount >= total_amount, 'completed', 'active'),
            completed_date = IF(paid_amount + p_amount >= total_amount, p_payment_date, NULL)
        WHERE id = p_long_pending_id;

        SELECT v_new_expense_id AS expense_id, 'success' AS status;
    ELSE
        SELECT NULL AS expense_id, 'invalid_amount' AS status;
    END IF;
END //

DELIMITER ;

-- ============================================
-- SAMPLE DATA MIGRATION QUERIES
-- (Based on the JSON structure provided)
-- ============================================

/*
-- Example: Insert user
INSERT INTO users (id, name, username, password_hash)
VALUES ('1763904760.105118', 'Dwaipayan Biswas', '8653640704', 'pbkdf2:sha256:600000$abg2vpS08UJZjiqZ$5d47726f036c456e1f3998ebc9b36b716fbf962bf7eddd55cfa9044d2e0e72f9');

-- Example: Insert accounts
INSERT INTO accounts (user_id, account_name, account_type) VALUES
('1763904760.105118', 'Cash', 'cash'),
('1763904760.105118', 'SBI-1', 'bank'),
('1763904760.105118', 'SBI-2', 'bank'),
('1763904760.105118', 'ALHB', 'bank');

-- Example: Insert categories
INSERT INTO categories (user_id, category_name, category_type) VALUES
('1763904760.105118', 'Bills', 'expense'),
('1763904760.105118', 'Food', 'expense'),
('1763904760.105118', 'Family', 'expense'),
('1763904760.105118', 'EMI', 'expense'),
('1763904760.105118', 'CC', 'expense'),
('1763904760.105118', 'Other', 'expense'),
('1763904760.105118', 'Savings', 'expense'),
('1763904760.105118', 'Bangalore', 'expense'),
('1763904760.105118', 'Social', 'expense'),
('1763904760.105118', 'Personal', 'expense');
*/

-- ============================================
-- INDEXES FOR PERFORMANCE
-- (Additional indexes for common queries)
-- ============================================

-- For date-range queries on expenses
CREATE INDEX idx_paid_expenses_date_range ON paid_expenses (user_id, expense_date);
CREATE INDEX idx_personal_expenses_date_range ON personal_expenses (user_id, expense_date);

-- For category analysis
CREATE INDEX idx_paid_expenses_category_analysis ON paid_expenses (user_id, month_id, category_id, amount);

-- ============================================
-- GRANTS (Adjust as needed)
-- ============================================

/*
-- Create application user
CREATE USER 'm_tracker_app'@'localhost' IDENTIFIED BY 'secure_password_here';

-- Grant privileges
GRANT SELECT, INSERT, UPDATE, DELETE ON m_tracker.* TO 'm_tracker_app'@'localhost';
GRANT EXECUTE ON m_tracker.* TO 'm_tracker_app'@'localhost';
FLUSH PRIVILEGES;
*/

-- ============================================
-- END OF SCHEMA
-- ============================================
