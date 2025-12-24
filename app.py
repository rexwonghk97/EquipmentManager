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

app = Flask(__name__)
app.secret_key = 'super_secret_key'

DATABASE = 'daci_database.db'
UPLOAD_FOLDER = 'static/icons'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# 確保圖片資料夾存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- 1. 資料庫連線 ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# --- 2. 輔助函數 ---

# Email 發送功能
def send_email_notification(request_id, loan_dt, return_dt, items):
    # ⚠️ 請填入你的 Gmail 設定，若無設定則只會印在 Terminal
    sender_email = "adadatasystem@gmail.com"
    sender_password = "pveq fqyt hmas pnyk" # Google App Password
    receiver_emails = ["rexwong2@ln.edu.hk", "tobbykan@ln.edu.hk"]


    subject = f"New Equipment Request: #{request_id}"
    
    # 建立郵件內容
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg['Subject'] = subject

    items_html = "<ul>"
    for item in items:
        items_html += f"<li>{item['name']} (Qty: {item['qty']})</li>"
    items_html += "</ul>"

    body = f"""
    <h3>New Equipment Request Received</h3>
    <p><strong>Request ID:</strong> {request_id}</p>
    <p><strong>Expected Loan:</strong> {loan_dt}</p>
    <p><strong>Expected Return:</strong> {return_dt}</p>
    <hr>
    <h4>Requested Items:</h4>
    {items_html}
    <p>Status: <strong>Pending</strong></p>
    <p>Please login to DACI E.Manager to review.</p>
    """
    
    msg.attach(MIMEText(body, 'html'))

    try:
        # 嘗試連線 Gmail
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_password)
        text = msg.as_string()
        server.sendmail(sender_email, receiver_email, text)
        server.quit()
        print(f"✅ Email notification for #{request_id} sent successfully.")
    except Exception as e:
        # 如果失敗 (例如沒設密碼)，只印出錯誤但不讓程式崩潰
        print(f"⚠️ Email sending skipped/failed: {e}")

# 前端圖片路徑輔助
@app.context_processor
def utility_processor():
    def get_icon_path(prefix, name):
        filename = f"{prefix}_{name}.png"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(filepath):
            return url_for('static', filename=f'icons/{filename}')
        return None
    return dict(get_icon_path=get_icon_path)

# 取得品牌列表 (包含新的排除名單)
def fetch_brands(category_filter='ALL'):
    conn = get_db()
    # 定義所有已知分類，用於 Others 的排除
    known_categories = [
        'Lights', 'Camera', 'Digital Tablet', 'Audio', 'MICs (Recording Studio)', 'VR Headset',
        'Stabilizer', 'Tripod', 'Filter', 'Lens', 'DACI Lighting Set', 'DACI Lighting Tripod'
    ]
    try:
        if category_filter != 'ALL':
            if category_filter == 'Others':
                placeholders = ','.join(['?'] * len(known_categories))
                query = f"SELECT DISTINCT Brand FROM Equipment_List WHERE Category NOT IN ({placeholders}) ORDER BY Brand"
                params = known_categories
            else:
                query = "SELECT DISTINCT Brand FROM Equipment_List WHERE Category = ? ORDER BY Brand"
                params = [category_filter]
            df = pd.read_sql_query(query, conn, params=params)
        else:
            query = "SELECT DISTINCT Brand FROM Equipment_List ORDER BY Brand"
            df = pd.read_sql_query(query, conn)
        return df['Brand'].tolist()
    except:
        return []

def fetch_types():
    conn = get_db()
    try:
        query = "SELECT DISTINCT Type FROM Equipment_List ORDER BY Type"
        df = pd.read_sql_query(query, conn)
        return df['Type'].tolist()
    except:
        return []

# 核心資料查詢
def fetch_equipment_data(availability='All', equipment_type='ALL', category_filter='ALL', brand_filter='ALL'):
    conn = get_db()
    query_conditions = []
    params = []
    
    known_categories = [
        'Lights', 'Camera', 'Digital Tablet', 'Audio', 'MICs (Recording Studio)', 'VR Headset',
        'Stabilizer', 'Tripod', 'Filter', 'Lens', 'DACI Lighting Set', 'DACI Lighting Tripod'
    ]

    if availability != 'All':
        query_conditions.append('Loan_History.Availability = ?')
        params.append(availability)

    if category_filter != 'ALL':
        if category_filter == 'Others':
            placeholders = ','.join(['?'] * len(known_categories))
            query_conditions.append(f"Equipment_List.Category NOT IN ({placeholders})")
            params.extend(known_categories)
        else:
            query_conditions.append("Equipment_List.Category = ?")
            params.append(category_filter)
            
    if equipment_type != 'ALL':
        query_conditions.append("Equipment_List.Type = ?")
        params.append(equipment_type)

    if brand_filter != 'ALL':
        query_conditions.append("Equipment_List.Brand = ?")
        params.append(brand_filter)

    availability_condition = ' AND '.join(query_conditions) if query_conditions else '1=1'

    query = f"""
    SELECT 
        Equipment_List.Equipment_ID AS ID,
        Equipment_List.Category, 
        Equipment_List.Type,
        Equipment_List.Name,
        Equipment_List.Brand,
        Equipment_List.Qty,
        Loan_History.Availability,
        Loan_History.Loan_From AS Loan_Start,
        Loan_History.Loan_Form_Number
    FROM Equipment_List
    JOIN Loan_History ON Equipment_List.Equipment_ID = Loan_History.Equipment_ID
    WHERE {availability_condition}
    """
    df = pd.read_sql_query(query, conn, params=params)
    return df

# --- 3. 路由 (Routes) ---

@app.route('/')
def index():
    return redirect(url_for('dashboard'))

@app.route('/login_action', methods=['POST'])
def login_action():
    name = request.form.get('name')
    password = request.form.get('password')
    if password == "0000":
        session['user'] = name
        flash(f'Welcome back, {name}!', 'success')
    else:
        flash('Invalid Password!', 'danger')
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('Logged out successfully.', 'info')
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    cat_filter = request.args.get('category', 'ALL')
    type_filter = request.args.get('type', 'ALL')
    brand_filter = request.args.get('brand', 'ALL')
    status_filter = request.args.get('status', 'All')
    
    status_map = {"All": "All", "Available Only": "Yes", "Unavailable Only": "No"}
    db_status = status_map.get(status_filter, "All")

    df_raw = fetch_equipment_data(db_status, type_filter, cat_filter, brand_filter)
    
    total = len(df_raw)
    avail = len(df_raw[df_raw['Availability'] == 'Yes'])
    loaned = len(df_raw[df_raw['Availability'] == 'No'])

    if not df_raw.empty:
        # 使用 agg 解決 Pandas FutureWarning
        df_display = df_raw.groupby(['Name', 'Brand', 'Type']).agg(
            Total_Qty=('Availability', 'count'),
            Avail_Qty=('Availability', lambda x: (x == 'Yes').sum()),
            Loaned_Qty=('Availability', lambda x: (x == 'No').sum())
        ).reset_index()
    else:
        df_display = pd.DataFrame()

    types = fetch_types()
    brands = fetch_brands(cat_filter)

    return render_template('dashboard.html', 
                           data=df_display.to_dict(orient='records'),
                           total=total, avail=avail, loaned=loaned,
                           types=types, brands=brands,
                           curr_cat=cat_filter, curr_type=type_filter, 
                           curr_brand=brand_filter, curr_status=status_filter)

# --- 購物車 API ---
@app.route('/api_update_cart', methods=['POST'])
def api_update_cart():
    data = request.json
    item_name = data.get('name')
    brand = data.get('brand')
    type_ = data.get('type')
    qty = int(data.get('qty', 0))
    
    if 'cart' not in session:
        session['cart'] = {}
    
    cart = session['cart']
    
    if qty > 0:
        cart[item_name] = {'name': item_name, 'brand': brand, 'type': type_, 'qty': qty}
    else:
        if item_name in cart:
            del cart[item_name]
    
    session.modified = True
    return {'status': 'success', 'total_items': len(cart), 'cart': cart}

@app.route('/api_clear_cart', methods=['POST'])
def api_clear_cart():
    session.pop('cart', None)
    return {'status': 'success'}

# --- [Generate Request] 申請單生成與處理 ---
@app.route('/generate_request', methods=['POST'])
def generate_request():
    # 1. 取得日期與時間
    loan_date = request.form.get('expected_loan_date')
    loan_time = request.form.get('expected_loan_time')
    return_date = request.form.get('expected_return_date')
    return_time = request.form.get('expected_return_time')
    
    # 2. 檢查購物車
    cart = session.get('cart', {})
    if not cart:
        flash('Your request list is empty. Please add items first.', 'warning')
        return redirect(url_for('dashboard'))
    
    # 3. 檢查必填欄位
    if not (loan_date and loan_time and return_date and return_time):
        flash('Please fill in ALL Date and Time fields.', 'warning')
        return redirect(url_for('dashboard'))

    request_items = list(cart.values())
    request_id = str(random.randint(10000000, 99999999))
    create_date = date.today().strftime("%Y-%m-%d")

    # 4. 存入 Request_Records (Pending 狀態)
    conn = get_db()
    items_json = json.dumps(request_items) 
    
    try:
        conn.execute("""
            INSERT INTO Request_Records (Request_ID, Loan_Date, Loan_Time, Return_Date, Return_Time, Items_Json, Status, Created_At)
            VALUES (?, ?, ?, ?, ?, ?, 'Pending', ?)
        """, (request_id, loan_date, loan_time, return_date, return_time, items_json, create_date))
        conn.commit()
    except sqlite3.OperationalError:
        flash("Error: Database missing 'Request_Records' table. Please run update_db_v3.py.", "danger")
    except Exception as e:
        flash(f'Error saving request: {e}', 'danger')

    # 5. 發送 Email (非同步或錯誤處理)
    loan_dt_str = f"{loan_date} {loan_time}"
    return_dt_str = f"{return_date} {return_time}"
    send_email_notification(request_id, loan_dt_str, return_dt_str, request_items)

    # 6. 清空購物車
    session.pop('cart', None)

    return render_template('request_summary.html', 
                           request_id=request_id, 
                           create_date=create_date,
                           loan_date=loan_date,
                           loan_time=loan_time,
                           return_date=return_date,
                           return_time=return_time,
                           items=request_items)

# --- Loan & Return (Staff Only) ---
@app.route('/loan_return', methods=['GET', 'POST'])
def loan_return():
    if 'user' not in session: 
        flash('Please login to access Loan & Return features.', 'warning')
        return redirect(url_for('dashboard'))
    
    conn = get_db()
    cat_filter = request.args.get('category', 'ALL')
    brand_filter = request.args.get('brand', 'ALL')
    
    if request.method == 'POST':
        action = request.form.get('action')
        selected_ids = request.form.getlist('equipment_ids') 
        
        if action == 'loan':
            loan_date = request.form.get('loan_date', date.today())
            form_number = request.form.get('loan_form_number')
            
            if not form_number:
                flash('Error: Loan Form Number is required!', 'danger')
                return redirect(url_for('loan_return', category=cat_filter, brand=brand_filter))
            
            if selected_ids:
                for eid in selected_ids:
                    # Update History
                    conn.execute("UPDATE Loan_History SET Availability = 'No', Loan_From = ?, Loan_Form_Number = ? WHERE Equipment_ID = ?", (loan_date, form_number, eid))
                    # Record Transaction
                    conn.execute("""
                        INSERT INTO Loan_Transactions (Loan_Form_Number, Equipment_ID, Loan_Date, Status) 
                        VALUES (?, ?, ?, 'Active')
                    """, (form_number, eid, loan_date))
                conn.commit()
                flash(f'Success! {len(selected_ids)} items loaned under Form #{form_number}.', 'success')
            else:
                 flash('Please select at least one item.', 'warning')
        
        elif action == 'return':
            if selected_ids:
                return_date = date.today()
                for eid in selected_ids:
                    # Update History
                    conn.execute("UPDATE Loan_History SET Availability = 'Yes', Loan_From = NULL, Loan_Form_Number = NULL WHERE Equipment_ID = ?", (eid,))
                    # Update Transaction
                    conn.execute("""
                        UPDATE Loan_Transactions 
                        SET Return_Date = ?, Status = 'Returned'
                        WHERE Equipment_ID = ? AND Status = 'Active'
                    """, (return_date, eid))
                conn.commit()
                flash(f'Success! {len(selected_ids)} items returned.', 'success')
            else:
                flash('Please select at least one item.', 'warning')
            
        return redirect(url_for('loan_return', category=cat_filter, brand=brand_filter))

    brands = fetch_brands(cat_filter)
    available_data = fetch_equipment_data(availability='Yes', category_filter=cat_filter, brand_filter=brand_filter).to_dict(orient='records')
    loaned_data = fetch_equipment_data(availability='No', category_filter=cat_filter, brand_filter=brand_filter).to_dict(orient='records')

    return render_template('loan_return.html', avail=available_data, loaned=loaned_data, curr_cat=cat_filter, curr_brand=brand_filter, brands=brands)

# --- Loan Forms Record (Pending + History) ---
@app.route('/loan_forms')
def loan_forms():
    if 'user' not in session: return redirect(url_for('dashboard'))

    conn = get_db()
    
    # Part 1: Pending Requests
    pending_forms = []
    try:
        # 檢查 Request_Records 表是否存在
        df_pending = pd.read_sql_query("SELECT * FROM Request_Records WHERE Status = 'Pending' ORDER BY Created_At DESC", conn)
        if not df_pending.empty:
            for _, row in df_pending.iterrows():
                items = json.loads(row['Items_Json'])
                pending_forms.append({
                    'id': row['Request_ID'],
                    'loan_dt': f"{row['Loan_Date']} {row['Loan_Time']}",
                    'return_dt': f"{row['Return_Date']} {row['Return_Time']}",
                    'items': items,
                    'count': sum(i['qty'] for i in items),
                    'status': 'Pending'
                })
    except Exception:
        # 如果表不存在，忽略 Pending 部分
        pass

    # Part 2: Active & History
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
                    'loan_dt': loan_date,
                    'items': group.to_dict(orient='records'),
                    'count': len(group),
                    'status': 'Complete' if is_complete else 'Active',
                    'is_complete': is_complete
                }
    except Exception:
        pass
    
    return render_template('loan_forms.html', pending=pending_forms, history=history_forms)

# --- 圖片上傳 (50x50) ---
@app.route('/upload_images', methods=['GET', 'POST'])
def upload_images():
    if 'user' not in session: return redirect(url_for('dashboard'))
    
    brands = fetch_brands('ALL')
    categories = ['Lights', 'Camera', 'Digital Tablet', 'Audio', 'VR Headset', 'Stabilizer', 'Tripod', 'Filter', 'Lens', 'DACI Lighting Set', 'DACI Lighting Tripod', 'Others']

    if request.method == 'POST':
        upload_type = request.form.get('upload_type')
        target_name = request.form.get('target_name')
        file = request.files['image_file']

        if file and target_name:
            try:
                img = Image.open(file)
                img = img.resize((50, 50), Image.Resampling.LANCZOS)
                
                prefix = "cat" if upload_type == "category" else "brand"
                filename = f"{prefix}_{target_name}.png"
                
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                img.save(save_path)
                
                flash(f'Image for {target_name} uploaded and resized (50x50px)!', 'success')
            except Exception as e:
                flash(f'Error processing image: {str(e)}', 'danger')
        
        return redirect(url_for('upload_images'))

    return render_template('upload_images.html', brands=brands, categories=categories)

# --- 資料庫管理 ---
@app.route('/db_manage', methods=['GET', 'POST'])
def db_manage():
    if 'user' not in session: return redirect(url_for('dashboard'))
    conn = get_db()
    
    if request.method == 'POST' and 'delete_id' in request.form:
        delete_id = request.form.get('delete_id')
        try:
            conn.execute("DELETE FROM Loan_History WHERE Equipment_ID = ?", (delete_id,))
            conn.execute("DELETE FROM Equipment_List WHERE Equipment_ID = ?", (delete_id,))
            conn.commit()
            flash(f'Item {delete_id} deleted successfully.', 'success')
        except Exception as e:
            flash(f'Error deleting: {e}', 'danger')
        return redirect(url_for('db_manage'))

    if request.method == 'POST' and 'add_item' in request.form:
        new_id = request.form.get('new_id')
        name = request.form.get('name')
        brand = request.form.get('brand')
        type_ = request.form.get('type')
        category = request.form.get('category')
        qty = request.form.get('qty', 1)
        
        try:
            conn.execute("""
                INSERT INTO Equipment_List (Equipment_ID, Name, Brand, Type, Category, Qty, item_created)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (new_id, name, brand, type_, category, qty, date.today()))
            
            conn.execute("""
                INSERT INTO Loan_History (Equipment_ID, Availability)
                VALUES (?, 'Yes')
            """, (new_id,))
            
            conn.commit()
            flash(f'Item {new_id} added successfully!', 'success')
        except sqlite3.IntegrityError:
            flash(f'Error: ID {new_id} already exists!', 'danger')
        except Exception as e:
            flash(f'Error adding item: {e}', 'danger')
        return redirect(url_for('db_manage'))

    df = pd.read_sql_query("SELECT * FROM Equipment_List ORDER BY item_created DESC", conn)
    existing_brands = fetch_brands('ALL')
    existing_types = fetch_types()
    return render_template('db_manage.html', items=df.to_dict(orient='records'), brands=existing_brands, types=existing_types)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
