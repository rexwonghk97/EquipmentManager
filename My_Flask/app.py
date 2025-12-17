from flask import Flask, render_template, request, redirect, url_for, session, g, flash
import sqlite3
import pandas as pd
from datetime import date
import random # 用於生成隨機 8 位數

app = Flask(__name__)
app.secret_key = 'super_secret_key'

DATABASE = 'daci_database.db'

# --- 資料庫連線 ---
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

# --- 輔助函數 ---
def fetch_brands(category_filter='ALL'):
    conn = get_db()
    try:
        if category_filter != 'ALL':
            if category_filter == 'Others':
                query = "SELECT DISTINCT Brand FROM Equipment_List WHERE Category NOT IN ('Lights', 'Camera', 'Digital Tablet', 'Audio', 'MICs (Recording Studio)') ORDER BY Brand"
                params = []
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

def fetch_equipment_data(availability='All', equipment_type='ALL', category_filter='ALL', brand_filter='ALL'):
    conn = get_db()
    query_conditions = []
    params = []

    if availability != 'All':
        query_conditions.append('Loan_History.Availability = ?')
        params.append(availability)

    if category_filter != 'ALL':
        if category_filter == 'Others':
            query_conditions.append("Equipment_List.Category NOT IN ('Lights', 'Camera', 'Digital Tablet', 'Audio', 'MICs (Recording Studio)')")
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

# --- 路由 ---

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
        df_display = df_raw.groupby(['Name', 'Brand', 'Type']).apply(
            lambda x: pd.Series({
                'Total_Qty': len(x),
                'Avail_Qty': (x['Availability'] == 'Yes').sum(),
                'Loaned_Qty': (x['Availability'] == 'No').sum()
            })
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

# [新功能] 生成申請單 (Dashboard 提交的表單)
@app.route('/generate_request', methods=['POST'])
def generate_request():
    # 取得 Dashboard 表單提交的數量
    # form data 結構類似: {'Sony A74': '2', 'Canon Lens': '0', ...}
    # 我們需要遍歷表單資料
    
    request_items = []
    
    for key, value in request.form.items():
        # HTML input name 是 "qty_器材名稱", 我們需要解析它
        if key.startswith('qty_') and value:
            try:
                qty = int(value)
                if qty > 0:
                    item_name = key.replace('qty_', '') # 取得器材名稱
                    request_items.append({'name': item_name, 'qty': qty})
            except ValueError:
                continue

    if not request_items:
        flash('Please select at least one item quantity.', 'warning')
        return redirect(url_for('dashboard'))

    # 生成 8 位數隨機號碼
    request_id = str(random.randint(10000000, 99999999))
    current_date = date.today().strftime("%Y-%m-%d")

    return render_template('request_summary.html', 
                           request_id=request_id, 
                           date=current_date, 
                           items=request_items)

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
                    # 1. 更新當前狀態
                    conn.execute("UPDATE Loan_History SET Availability = 'No', Loan_From = ?, Loan_Form_Number = ? WHERE Equipment_ID = ?", (loan_date, form_number, eid))
                    
                    # 2. [新增] 寫入交易紀錄表 (Status = Active)
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
                    # 1. 更新當前狀態 (變回 Available, 清空單號)
                    conn.execute("UPDATE Loan_History SET Availability = 'Yes', Loan_From = NULL, Loan_Form_Number = NULL WHERE Equipment_ID = ?", (eid,))
                    
                    # 2. [新增] 更新交易紀錄表 (找到該設備最近一筆 Active 的紀錄，標記為 Returned)
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

    return render_template('loan_return.html', 
                           avail=available_data, 
                           loaned=loaned_data, 
                           curr_cat=cat_filter,
                           curr_brand=brand_filter,
                           brands=brands)

# --- Loan Forms Record (改寫：讀取永久紀錄) ---
@app.route('/loan_forms')
def loan_forms():
    if 'user' not in session: return redirect(url_for('dashboard'))

    conn = get_db()
    # 查詢 Loan_Transactions 加上 Equipment Info
    query = """
    SELECT 
        T.Loan_Form_Number,
        T.Loan_Date,
        T.Return_Date,
        T.Status,
        E.Name,
        E.Brand,
        E.Type,
        T.Equipment_ID
    FROM Loan_Transactions T
    JOIN Equipment_List E ON T.Equipment_ID = E.Equipment_ID
    ORDER BY T.Loan_Date DESC, T.Loan_Form_Number
    """
    df = pd.read_sql_query(query, conn)
    
    forms = {}
    if not df.empty:
        # 依單號分組
        grouped = df.groupby(['Loan_Form_Number', 'Loan_Date'])
        for (form_num, loan_date), group in grouped:
            
            # 判斷該單號是否 "Complete"
            # 如果該單號下所有 item 的 Status 都是 'Returned'，則整單完成
            active_count = len(group[group['Status'] == 'Active'])
            is_complete = (active_count == 0)
            
            forms[form_num] = {
                'date': loan_date,
                'items': group.to_dict(orient='records'),
                'count': len(group),
                'is_complete': is_complete, # 用於前端顯示勾勾
                'status_label': 'Complete' if is_complete else 'Active'
            }
    
    return render_template('loan_forms.html', forms=forms)

if __name__ == '__main__':
    app.run(debug=True, port=5000)