import os
from flask import Flask, render_template, request, redirect, url_for, session, g, flash
import sqlite3
import pandas as pd
from datetime import date
import random
from PIL import Image  # 用於圖片處理

app = Flask(__name__)
app.secret_key = 'super_secret_key'

DATABASE = 'daci_database.db'
UPLOAD_FOLDER = 'static/icons' # 圖片儲存路徑
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# 確保圖片資料夾存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

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

# [新功能] 檢查圖片是否存在
# 這讓前端可以判斷：如果 user 上傳了圖片就用圖片，沒上傳就用預設 Icon
@app.context_processor
def utility_processor():
    def get_icon_path(prefix, name):
        # 檔名規則: cat_Lights.png 或 brand_Sony.png
        filename = f"{prefix}_{name}.png"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        # 檢查檔案是否存在
        if os.path.exists(filepath):
            return url_for('static', filename=f'icons/{filename}')
        return None
    return dict(get_icon_path=get_icon_path)

def fetch_brands(category_filter='ALL'):
    conn = get_db()
    try:
        if category_filter != 'ALL':
            if category_filter == 'Others':
                query = "SELECT DISTINCT Brand FROM Equipment_List WHERE Category NOT IN ('Lights', 'Camera', 'Digital Tablet', 'Audio', 'MICs (Recording Studio)', 'VR Headset', 'Stabilizer', 'Tripod', 'Filter', 'Lens', 'DACI Lighting Set', 'DACI Lighting Tripod') ORDER BY Brand"
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
            query_conditions.append("Equipment_List.Category NOT IN ('Lights', 'Camera', 'Digital Tablet', 'Audio', 'MICs (Recording Studio)', 'VR Headset', 'Stabilizer', 'Tripod', 'Filter', 'Lens', 'DACI Lighting Set', 'DACI Lighting Tripod')")
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

@app.route('/generate_request', methods=['POST'])
def generate_request():
    request_items = []
    for key, value in request.form.items():
        if key.startswith('qty_') and value:
            try:
                qty = int(value)
                if qty > 0:
                    item_name = key.replace('qty_', '')
                    request_items.append({'name': item_name, 'qty': qty})
            except ValueError:
                continue

    if not request_items:
        flash('Please select at least one item quantity.', 'warning')
        return redirect(url_for('dashboard'))

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
                    conn.execute("UPDATE Loan_History SET Availability = 'No', Loan_From = ?, Loan_Form_Number = ? WHERE Equipment_ID = ?", (loan_date, form_number, eid))
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
                    conn.execute("UPDATE Loan_History SET Availability = 'Yes', Loan_From = NULL, Loan_Form_Number = NULL WHERE Equipment_ID = ?", (eid,))
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

@app.route('/loan_forms')
def loan_forms():
    if 'user' not in session: return redirect(url_for('dashboard'))

    conn = get_db()
    query = """
    SELECT T.Loan_Form_Number, T.Loan_Date, T.Return_Date, T.Status, E.Name, E.Brand, E.Type, T.Equipment_ID
    FROM Loan_Transactions T JOIN Equipment_List E ON T.Equipment_ID = E.Equipment_ID
    ORDER BY T.Loan_Date DESC, T.Loan_Form_Number
    """
    df = pd.read_sql_query(query, conn)
    
    forms = {}
    if not df.empty:
        grouped = df.groupby(['Loan_Form_Number', 'Loan_Date'])
        for (form_num, loan_date), group in grouped:
            active_count = len(group[group['Status'] == 'Active'])
            is_complete = (active_count == 0)
            forms[form_num] = {
                'date': loan_date,
                'items': group.to_dict(orient='records'),
                'count': len(group),
                'is_complete': is_complete,
                'status_label': 'Complete' if is_complete else 'Active'
            }
    
    return render_template('loan_forms.html', forms=forms)

# --- [新功能 1] 圖片上傳 (Resize 20x20) ---
@app.route('/upload_images', methods=['GET', 'POST'])
def upload_images():
    if 'user' not in session: return redirect(url_for('dashboard'))
    
    brands = fetch_brands('ALL')
    categories = ['Lights', 'Camera', 'Digital Tablet', 'Audio', 'VR Headset', 'Stabilizer', 'Tripod', 'Filter', 'Lens', 'DACI Lighting Set', 'DACI Lighting Tripod', 'Others']

    if request.method == 'POST':
        upload_type = request.form.get('upload_type') # 'category' or 'brand'
        target_name = request.form.get('target_name') # 例如 'Camera' 或 'Sony'
        file = request.files['image_file']

        if file and target_name:
            try:
                # 1. 開啟並壓縮圖片
                img = Image.open(file)
                # 使用 thumbnail 或 resize 來縮小，並保持品質
                img = img.resize((50, 50), Image.Resampling.LANCZOS)
                
                # 2. 定義檔名 (cat_Name.png 或 brand_Name.png)
                prefix = "cat" if upload_type == "category" else "brand"
                filename = f"{prefix}_{target_name}.png"
                
                # 3. 儲存
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                img.save(save_path)
                
                flash(f'Image for {target_name} uploaded and resized (50x50px)!', 'success')
            except Exception as e:
                flash(f'Error processing image: {str(e)}', 'danger')
        
        return redirect(url_for('upload_images'))

    return render_template('upload_images.html', brands=brands, categories=categories)

# --- [新功能 2] 資料庫管理 (Add/Delete) ---
@app.route('/db_manage', methods=['GET', 'POST'])
def db_manage():
    if 'user' not in session: return redirect(url_for('dashboard'))
    
    conn = get_db()
    
    # 處理刪除
    if request.method == 'POST' and 'delete_id' in request.form:
        delete_id = request.form.get('delete_id')
        try:
            # 刪除 Equipment_List (Loan_History 和 Transactions 保留或聯動刪除視需求，這裡做安全刪除)
            # 先刪除 Loan_History 以免孤兒資料 (或使用 FK cascade，但這裡手動處理較保險)
            conn.execute("DELETE FROM Loan_History WHERE Equipment_ID = ?", (delete_id,))
            conn.execute("DELETE FROM Equipment_List WHERE Equipment_ID = ?", (delete_id,))
            conn.commit()
            flash(f'Item {delete_id} deleted successfully.', 'success')
        except Exception as e:
            flash(f'Error deleting: {e}', 'danger')
        return redirect(url_for('db_manage'))

    # 處理新增
    if request.method == 'POST' and 'add_item' in request.form:
        new_id = request.form.get('new_id')
        name = request.form.get('name')
        brand = request.form.get('brand')
        type_ = request.form.get('type')
        category = request.form.get('category')
        qty = request.form.get('qty', 1)
        
        try:
            # 1. 插入 Equipment_List
            conn.execute("""
                INSERT INTO Equipment_List (Equipment_ID, Name, Brand, Type, Category, Qty, item_created)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (new_id, name, brand, type_, category, qty, date.today()))
            
            # 2. 插入初始 Loan_History (Availability = Yes)
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

    # 讀取目前資料庫所有項目 (供刪除列表用)
    df = pd.read_sql_query("SELECT * FROM Equipment_List ORDER BY item_created DESC", conn)
    
    # 用於新增選單的現有選項
    existing_brands = fetch_brands('ALL')
    existing_types = fetch_types()
    
    return render_template('db_manage.html', items=df.to_dict(orient='records'), brands=existing_brands, types=existing_types)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
@app.route('/api_update_cart', methods=['POST'])
def api_update_cart():
    """ 接收前端傳來的商品，存入 Session """
    data = request.json
    item_name = data.get('name')
    brand = data.get('brand')
    type_ = data.get('type')
    qty = int(data.get('qty', 0))
    
    # 初始化購物車
    if 'cart' not in session:
        session['cart'] = {}
    
    cart = session['cart']
    
    if qty > 0:
        # 更新或新增
        cart[item_name] = {
            'name': item_name,
            'brand': brand,
            'type': type_,
            'qty': qty
        }
    else:
        # 如果數量為 0，則移除該項目
        if item_name in cart:
            del cart[item_name]
    
    session.modified = True
    
    # 回傳目前購物車總共有幾項物品 (用於更新前端顯示)
    total_items = len(cart)
    return {'status': 'success', 'total_items': total_items, 'cart': cart}

@app.route('/api_clear_cart', methods=['POST'])
def api_clear_cart():
    session.pop('cart', None)
    return {'status': 'success'}

# --- [修改] 生成申請單 (改為從 Session 讀取 + 接收日期) ---
@app.route('/generate_request', methods=['POST'])
def generate_request():
    # 1. 取得日期
    loan_date = request.form.get('expected_loan_date')
    return_date = request.form.get('expected_return_date')
    
    # 2. 從 Session 取得購物車內容
    cart = session.get('cart', {})
    
    if not cart:
        flash('Your request list is empty. Please add items first.', 'warning')
        return redirect(url_for('dashboard'))
    
    if not loan_date or not return_date:
        flash('Please select both Loan and Return dates.', 'warning')
        return redirect(url_for('dashboard'))

    # 轉換格式給 template 使用
    request_items = list(cart.values()) # [{'name':..., 'qty':...}, ...]

    # 生成 8 位數隨機號碼
    request_id = str(random.randint(10000000, 99999999))
    create_date = date.today().strftime("%Y-%m-%d")

    # (可選) 生成後是否清空購物車？通常生成單據後可以清空
    # session.pop('cart', None) 

    return render_template('request_summary.html', 
                           request_id=request_id, 
                           create_date=create_date,
                           loan_date=loan_date,     # [新增]
                           return_date=return_date, # [新增]
                           items=request_items)
