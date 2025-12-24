import sqlite3

conn = sqlite3.connect('daci_database.db')
cursor = conn.cursor()

# 建立 Request_Records 表 (儲存 Pending 訂單)
cursor.execute("""
CREATE TABLE IF NOT EXISTS Request_Records (
    Request_ID TEXT PRIMARY KEY,
    Loan_Date TEXT,
    Loan_Time TEXT,
    Return_Date TEXT,
    Return_Time TEXT,
    Items_Json TEXT, -- 用 JSON 字串存儲器材和數量 (例如: "Sony A74: 2, Tripod: 1")
    Status TEXT,     -- 'Pending'
    Created_At TEXT
)
""")

print("✅ 資料庫升級完成：新增 Request_Records 表格")
conn.commit()
conn.close()