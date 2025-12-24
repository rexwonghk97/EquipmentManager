import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template, request, redirect, url_for, session, g, flash
import sqlite3
import pandas as pd
from datetime import date, datetime
import random
from PIL import Image

# ... (前面的設定與 get_db, fetch 函式保持不變) ...

# --- [新功能] Email 發送函式 ---
def send_email_notification(request_id, loan_dt, return_dt, items):
    # ⚠️ 設定你的 Email (建議使用 Gmail App Password)
    sender_email = "your_email@gmail.com" 
    sender_password = "emyz ywqt ovnu xeco" # 不是你的登入密碼，是 Google 帳戶設定裡的 App Password
    receiver_email = "rexwong2@ln.edu.hk"

    subject = f"New Equipment Request: #{request_id}"
    
    # 建立郵件內容
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg['Subject'] = subject

    # 格式化物品清單
    items_html = "<ul>"
    for item in items:
        items_html += f"<li>{item['name']} (Qty: {item['qty']})</li>"
    items_html += "</ul>"

    body = f"""
    <h3>New Equipment Request Received</h3>
    <p><strong>Request ID:</strong> {request_id}</p>
    <p><strong>Loan Time:</strong> {loan_dt}</p>
    <p><strong>Return Time:</strong> {return_dt}</p>
    <hr>
    <h4>Requested Items:</h4>
    {items_html}
    <p>Please login to DACI E.Manager to review.</p>
    """
    
    msg.attach(MIMEText(body, 'html'))

    try:
        # 使用 Gmail SMTP Server
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_password)
        text = msg.as_string()
        server.sendmail(sender_email, receiver_email, text)
        server.quit()
        print("✅ Email sent successfully")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")

# --- [修改] 生成申請單 (加入時間、存DB、寄信) ---
@app.route('/generate_request', methods=['POST'])
def generate_request():
    # 1. 取得日期與時間
    loan_date = request.form.get('expected_loan_date')
    loan_time = request.form.get('expected_loan_time') # [新增]
    return_date = request.form.get('expected_return_date')
    return_time = request.form.get('expected_return_time') # [新增]
    
    cart = session.get('cart', {})
    
    if not cart:
        flash('Your request list is empty.', 'warning')
        return redirect(url_for('dashboard'))
    
    if not (loan_date and loan_time and return_date and return_time):
        flash('Please fill in ALL Date and Time fields.', 'warning')
        return redirect(url_for('dashboard'))

    request_items = list(cart.values())
    request_id = str(random.randint(10000000, 99999999))
    create_date = date.today().strftime("%Y-%m-%d")

    # 2. [新增] 存入資料庫 (作為 Pending 訂單)
    conn = get_db()
    
    # 將物品列表轉為 JSON 字串儲存
    items_json = json.dumps(request_items) 
    
    try:
        conn.execute("""
            INSERT INTO Request_Records (Request_ID, Loan_Date, Loan_Time, Return_Date, Return_Time, Items_Json, Status, Created_At)
            VALUES (?, ?, ?, ?, ?, ?, 'Pending', ?)
        """, (request_id, loan_date, loan_time, return_date, return_time, items_json, create_date))
        conn.commit()
    except Exception as e:
        flash(f'Error saving request: {e}', 'danger')

    # 3. [新增] 發送 Email (非同步處理最好，但這裡簡單直接發)
    # 為了避免沒設密碼導致報錯卡住，我們用 try-except 包在函式裡了
    loan_dt_str = f"{loan_date} {loan_time}"
    return_dt_str = f"{return_date} {return_time}"
    send_email_notification(request_id, loan_dt_str, return_dt_str, request_items)

    # 4. 清空購物車 (可選，看你是否希望提交後清空)
    session.pop('cart', None)

    return render_template('request_summary.html', 
                           request_id=request_id, 
                           create_date=create_date,
                           loan_date=loan_date,
                           loan_time=loan_time,     # [傳入前端]
                           return_date=return_date,
                           return_time=return_time, # [傳入前端]
                           items=request_items)

# --- [修改] Loan Forms Record (顯示 Pending + History) ---
@app.route('/loan_forms')
def loan_forms():
    if 'user' not in session: return redirect(url_for('dashboard'))

    conn = get_db()
    
    # Part A: 抓取 Pending Requests (新表)
    pending_forms = []
    try:
        df_pending = pd.read_sql_query("SELECT * FROM Request_Records WHERE Status = 'Pending' ORDER BY Created_At DESC", conn)
        if not df_pending.empty:
            for _, row in df_pending.iterrows():
                # 解析 JSON 物品清單
                items = json.loads(row['Items_Json'])
                pending_forms.append({
                    'id': row['Request_ID'],
                    'loan_dt': f"{row['Loan_Date']} {row['Loan_Time']}",
                    'return_dt': f"{row['Return_Date']} {row['Return_Time']}",
                    'items': items,
                    'count': sum(i['qty'] for i in items),
                    'status': 'Pending'
                })
    except Exception as e:
        print(f"Error fetching pending: {e}")

    # Part B: 抓取 Active/Complete Loans (舊表)
    history_forms = {}
    try:
        query = """
        SELECT T.Loan_Form_Number, T.Loan_Date, T.Return_Date, T.Status, E.Name, E.Brand, E.Type, T.Equipment_ID
        FROM Loan_Transactions T JOIN Equipment_List E ON T.Equipment_ID = E.Equipment_ID
        ORDER BY T.Loan_Date DESC, T.Loan_Form_Number
        """
        df = pd.read_sql_query(query, conn)
        
        if not df.empty:
            grouped = df.groupby(['Loan_Form_Number', 'Loan_Date'])
            for (form_num, loan_date), group in grouped:
                active_count = len(group[group['Status'] == 'Active'])
                is_complete = (active_count == 0)
                history_forms[form_num] = {
                    'id': form_num,
                    'loan_dt': loan_date, # 舊表沒有存時間，只存日期
                    'items': group.to_dict(orient='records'),
                    'count': len(group),
                    'status': 'Complete' if is_complete else 'Active',
                    'is_complete': is_complete
                }
    except Exception as e:
        print(f"Error fetching history: {e}")
    
    return render_template('loan_forms.html', pending=pending_forms, history=history_forms)
