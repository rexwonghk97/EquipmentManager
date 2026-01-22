import os
import json
# [移除] Email 相關的 import
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

# [移除] def send_email_notification(...) 整段已被刪除

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

# 取得品牌列表
def fetch_brands(category_filter='ALL'):
    conn = get_db()
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

# 核心資料查詢 (含搜尋功能)
def fetch_equipment_data(availability='All', equipment_type='ALL', category_filter='ALL', brand_filter='ALL', search_query=''):
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

    # [搜尋功能]
    if search_query:
        query_conditions.append("(Equipment_List.Name LIKE ? OR Equipment_List.Brand LIKE ? OR Equipment_List.Equipment_ID LIKE ?)")
        search_term = f"%{search_query}%"
        params.extend([search_term, search_term, search_term])

    availability_condition = ' AND '.join(query_conditions) if query_conditions else '1=1'

    query = f"""
    SELECT 
        Equipment_List.Equipment_ID AS ID,
        Equipment_List.Category, 
        Equipment_List.Type,
        Equipment_List.Name,
        Equipment_List.Brand,
        Equipment_List.Qty,
        Equipment_List.Remarks,
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

# --- Dashboard (含 Pending 計算) ---
@app.route('/dashboard')
def dashboard():
    cat_filter = request.args.get('category', 'ALL')
    type_filter = request.args.get('type', 'ALL')
    brand_filter = request.args.get('brand', 'ALL')
    status_filter = request.args.get('status', 'All')
    search_query = request.args.get('search', '')
    
    status_map = {"All": "All", "Available Only": "Yes", "Unavailable Only": "No"}
    db_status = status_map.get(status_filter, "All")

    conn = get_db()
    
    # 1. 取得物理庫存
    df_raw = fetch_equipment_data(db_status, type_filter, cat_filter, brand_filter, search_query)
    
    # 2. 計算 Pending (被預訂) 數量
    pending_map = {} 
    total_pending_count = 0
    try:
        df_req = pd.read_sql_query("SELECT Items_Json FROM Request_Records WHERE Status = 'Pending'", conn)
        for json_str in df_req['Items_Json']:
            try:
                items = json.loads(json_str)
                for i in items:
                    name = i['name']
                    qty = int(i['qty'])
                    pending_map[name] = pending_map.get(name, 0) + qty
                    total_pending_count += qty
            except:
                continue
    except:
        pass 

    # 3. 整合資料
    final_data = []
    total_assets = 0
    physical_loaned_total = 0
    
    if not df_raw.empty:
        grouped = df_raw.groupby(['Name', 'Brand', 'Type', 'Category']).agg(
            Representative_ID=('ID', 'first'),
            Total_Qty=('Availability', 'count'),
            Physical_Avail=('Availability', lambda x: (x == 'Yes').sum()),
            Physical_Loaned=('Availability', lambda x: (x == 'No').sum())
        ).reset_index()
        
        for _, row in grouped.iterrows():
            name = row['Name']
            p_qty = pending_map.get(name, 0)
            
            # 淨可用 = 物理可用 - 預訂
            net_avail = row['Physical_Avail'] - p_qty
            if net_avail < 0: net_avail = 0 
            
            final_data.append({
                'Name': name,
                'Brand': row['Brand'],
                'Type': row['Type'],
                'Category': row['Category'],
                'Rep_ID': row['Representative_ID'],
                'Total_Qty': row['Total_Qty'],
                'Physical_Avail': row['Physical_Avail'],
                'Loaned_Qty': row['Physical_Loaned'],
                'Pending_Qty': p_qty,
                'Net_Avail_Qty': net_avail
            })
            
            total_assets += row['Total_Qty']
            physical_loaned_total += row['Physical_Loaned']

    display_loaned = physical_loaned_total + total_pending_count
    display_avail = total_assets - display_loaned
    if display_avail < 0: display_avail = 0

    types = fetch_types()
    brands = fetch_brands(cat_filter)

    return render_template('dashboard.html', 
                           data=final_data,
                           total=total_assets, 
                           avail=display_avail, 
                           loaned=display_loaned,
                           types=types, brands=brands,
                           curr_cat=cat_filter, curr_type=type_filter, 
                           curr_brand=brand_filter, curr_status=status_filter,
                           curr_search=search_query)

# --- 購物車 API ---
@app.route('/api_update_cart', methods=['POST'])
def api_update_cart():
    data = request.json
    item_name = data.get('name')
    brand = data.get('brand')
    type_ = data.get('type')
    qty = int(data.get('qty', 0))
    
    if 'cart' not in session: session['cart'] = {}
    cart = session['cart']
    
    if qty > 0:
        cart[item_name] = {'name': item_name, 'brand': brand, 'type': type_, 'qty': qty}
    else:
        if item_name in cart: del cart[item_name]
    
    session.modified = True
    return {'status': 'success', 'total_items': len(cart), 'cart': cart}

@app.route('/api_clear_cart', methods=['POST'])
def api_clear_cart():
    session.pop('cart', None)
    return {'status': 'success'}

# --- Generate Request (Email 功能已移除) ---
@app.route('/generate_request', methods=['POST'])
def generate_request():
    loan_date = request.form.get('expected_loan_date')
    loan_time = request.form.get('expected_loan_time')
    return_date = request.form.get('expected_return_date')
    return_time = request.form.get('expected_return_time')
    
    cart = session.get('cart', {})
    if not cart:
        flash('Request list is empty.', 'warning')
        return redirect(url_for('dashboard'))
    
    if not (loan_date and loan_time and return_date and return_time):
        flash('Please fill in ALL Date and Time fields.', 'warning')
        return redirect(url_for('dashboard'))

    request_items = list(cart.values())
    request_id = str(random.randint(10000000, 99999999))
    create_date = date.today().strftime("%Y-%m-%d")

    conn = get_db()
    items_json = json.dumps(request_items) 
    
    try:
        conn.execute("""
            INSERT INTO Request_Records (Request_ID, Loan_Date, Loan_Time, Return_Date, Return_Time, Items_Json, Status, Created_At)
            VALUES (?, ?, ?, ?, ?, ?, 'Pending', ?)
        """, (request_id, loan_date, loan_time, return_date, return_time, items_json, create_date))
        conn.commit()
    except Exception as e:
        flash(f'Error saving request: {e}', 'danger')

    # [移除] 這裡原本呼叫 send_email_notification 的程式碼已刪除

    session.pop('cart', None)

    return render_template('request_summary.html', 
                           request_id=request_id, 
                           create_date=create_date,
                           loan_date=loan_date, loan_time=loan_time,
                           return_date=return_date, return_time=return_time,
                           items=request_items)

# --- 處理 Pending 狀態 ---
@app.route('/process_request/<request_id>/<action>')
def process_request(request_id, action):
    if 'user' not in session: return redirect(url_for('dashboard'))
    conn = get_db()
    new_status = 'Processed' if action == 'approve' else 'Rejected'
    try:
        conn.execute("UPDATE Request_Records SET Status = ? WHERE Request_ID = ?", (new_status, request_id))
        conn.commit()
        flash(f'Request #{request_id} marked as {new_status}.', 'success')
    except Exception as e:
        flash(f'Error updating request: {e}', 'danger')
    return redirect(url_for('loan_forms'))

# --- Loan & Return ---
@app.route('/loan_return', methods=['GET', 'POST'])
def loan_return():
    if 'user' not in session: 
        flash('Please login to access Loan & Return features.', 'warning')
        return redirect(url_for('dashboard'))
    
    conn = get_db()
    cat_filter = request.args.get('category', 'ALL')
    brand_filter = request.args.get('brand', 'ALL')
    search_query = request.args.get('search', '')
    
    if request.method == 'POST':
        action = request.form.get('action')
        selected_ids = request.form.getlist('equipment_ids') 
        
        if action == 'loan':
            loan_date = request.form.get('loan_date', date.today())
            form_number = request.form.get('loan_form_number')
            
            if not form_number:
                flash('Loan Form Number is required!', 'danger')
                return redirect(url_for('loan_return', category=cat_filter, brand=brand_filter, search=search_query))
            
            if selected_ids:
                for eid in selected_ids:
                    conn.execute("UPDATE Loan_History SET Availability = 'No', Loan_From = ?, Loan_Form_Number = ? WHERE Equipment_ID = ?", (loan_date, form_number, eid))
                    conn.execute("INSERT INTO Loan_Transactions (Loan_Form_Number, Equipment_ID, Loan_Date, Status) VALUES (?, ?, ?, 'Active')", (form_number, eid, loan_date))
                conn.commit()
                flash(f'Success! {len(selected_ids)} items loaned.', 'success')
            else:
                 flash('Please select at least one item.', 'warning')
        
        elif action == 'return':
            if selected_ids:
                return_date = date.today()
                for eid in selected_ids:
                    conn.execute("UPDATE Loan_History SET Availability = 'Yes', Loan_From = NULL, Loan_Form_Number = NULL WHERE Equipment_ID = ?", (eid,))
                    conn.execute("UPDATE Loan_Transactions SET Return_Date = ?, Status = 'Returned' WHERE Equipment_ID = ? AND Status = 'Active'", (return_date, eid))
                conn.commit()
                flash(f'Success! {len(selected_ids)} items returned.', 'success')
            else:
                flash('Please select at least one item.', 'warning')
            
        return redirect(url_for('loan_return', category=cat_filter, brand=brand_filter, search=search_query))

    brands = fetch_brands(cat_filter)
    available_data = fetch_equipment_data(availability='Yes', category_filter=cat_filter, brand_filter=brand_filter, search_query=search_query).to_dict(orient='records')
    loaned_data = fetch_equipment_data(availability='No', category_filter=cat_filter, brand_filter=brand_filter, search_query=search_query).to_dict(orient='records')

    return render_template('loan_return.html', avail=available_data, loaned=loaned_data, curr_cat=cat_filter, curr_brand=brand_filter, curr_search=search_query, brands=brands)

# --- Loan Forms ---
@app.route('/loan_forms')
def loan_forms():
    if 'user' not in session: return redirect(url_for('dashboard'))
    conn = get_db()
    
    pending_forms = []
    try:
        df_pending = pd.read_sql_query("SELECT * FROM Request_Records WHERE Status = 'Pending' ORDER BY Created_At DESC", conn)
        if not df_pending.empty:
            for _, row in df_pending.iterrows():
                try: items_list = json.loads(row['Items_Json'])
                except: items_list = []
                pending_forms.append({
                    'id': row['Request_ID'],
                    'loan_dt': f"{row['Loan_Date']} {row['Loan_Time']}",
                    'return_dt': f"{row['Return_Date']} {row['Return_Time']}",
                    'item_list': items_list,
                    'count': sum(i['qty'] for i in items_list),
                    'status': 'Pending'
                })
    except: pass

    history_forms = {}
    try:
        query = "SELECT T.Loan_Form_Number, T.Loan_Date, T.Return_Date, T.Status, E.Name, E.Brand, E.Type, T.Equipment_ID FROM Loan_Transactions T JOIN Equipment_List E ON T.Equipment_ID = E.Equipment_ID ORDER BY T.Loan_Date DESC, T.Loan_Form_Number"
        df = pd.read_sql_query(query, conn)
        if not df.empty:
            grouped = df.groupby(['Loan_Form_Number', 'Loan_Date'])
            for (form_num, loan_date), group in grouped:
                active_count = len(group[group['Status'] == 'Active'])
                is_complete = (active_count == 0)
                history_forms[form_num] = {
                    'id': form_num,
                    'loan_dt': loan_date,
                    'item_list': group.to_dict(orient='records'),
                    'count': len(group),
                    'is_complete': is_complete
                }
    except: pass
    
    return render_template('loan_forms.html', pending=pending_forms, history=history_forms)

# --- Upload Images ---
@app.route('/upload_images', methods=['GET', 'POST'])
def upload_images():
    if 'user' not in session: return redirect(url_for('dashboard'))
    brands = fetch_brands('ALL')
    categories = ['Lights', 'Camera', 'Digital Tablet', 'Audio', 'VR Headset', 'Stabilizer', 'Tripod', 'Filter', 'Lens', 'DACI Lighting Set', 'DACI Lighting Tripod', 'Others']
    conn = get_db()
    items_df = pd.read_sql_query("SELECT Equipment_ID, Name FROM Equipment_List ORDER BY Name", conn)
    all_items = items_df.to_dict(orient='records')

    if request.method == 'POST':
        upload_type = request.form.get('upload_type')
        target_name = request.form.get('target_name')
        file = request.files['image_file']
        if file and target_name:
            try:
                img = Image.open(file)
                if upload_type == 'item':
                    img = img.resize((60, 60), Image.Resampling.LANCZOS)
                    prefix = "item"
                else:
                    img = img.resize((50, 50), Image.Resampling.LANCZOS)
                    prefix = "cat" if upload_type == "category" else "brand"
                filename = f"{prefix}_{target_name}.png"
                img.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                flash(f'Image for {target_name} uploaded!', 'success')
            except Exception as e:
                flash(f'Error: {e}', 'danger')
        return redirect(url_for('upload_images'))
    return render_template('upload_images.html', brands=brands, categories=categories, all_items=all_items)

# --- DB Manage ---
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
            flash('Deleted successfully.', 'success')
        except Exception as e: flash(f'Error: {e}', 'danger')
        return redirect(url_for('db_manage'))

    if request.method == 'POST' and 'add_item' in request.form:
        new_id = request.form.get('new_id')
        name = request.form.get('name')
        brand = request.form.get('brand')
        type_ = request.form.get('type')
        category = request.form.get('category')
        qty = request.form.get('qty', 1)
        remarks = request.form.get('remarks', '')
        
        try:
            conn.execute("""
                INSERT INTO Equipment_List (Equipment_ID, Name, Brand, Type, Category, Remarks, Qty, item_created)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (new_id, name, brand, type_, category, remarks, qty, date.today()))
            
            conn.execute("""
                INSERT INTO Loan_History (Equipment_ID, Availability)
                VALUES (?, 'Yes')
            """, (new_id,))
            
            conn.commit()
            flash('Item added successfully!', 'success')
        except Exception as e: flash(f'Error: {e}', 'danger')
        return redirect(url_for('db_manage'))

    df = pd.read_sql_query("SELECT * FROM Equipment_List ORDER BY item_created DESC", conn)
    return render_template('db_manage.html', items=df.to_dict(orient='records'), brands=fetch_brands('ALL'), types=fetch_types())

if __name__ == '__main__':
    app.run(debug=True, port=5000)
