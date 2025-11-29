import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
import psycopg2
import sqlite3
import os
import tempfile

# --- إعداد الصفحة ---
st.set_page_config(page_title="Nawaem System", layout="wide", page_icon="📊", initial_sidebar_state="expanded")

# --- دالة توقيت بغداد ---
def get_baghdad_time():
    tz = pytz.timezone('Asia/Baghdad')
    return datetime.now(tz)

# --- CSS ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Cairo', sans-serif;
    }

    .stApp {direction: rtl;}

    div[data-testid="column"] {text-align: right;}

    .stButton button {
        width: 100%;
        height: 50px;
        border-radius: 12px;
        font-weight: bold;
        transition: all 0.3s ease;
    }

    div[data-testid="metric-container"] {
        background-color: #ffffff;
        padding: 15px;
        border-radius: 12px;
        text-align: center;
        border: 1px solid #e0e0e0;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }

    .sidebar-content {
        padding: 20px;
    }

    h1, h2, h3 {
        color: #e91e63; /* Pink shade */
    }
</style>
""", unsafe_allow_html=True)

# --- 1. إدارة الجلسة ---
if 'cart' not in st.session_state:
    st.session_state.cart = []
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'sale_success' not in st.session_state:
    st.session_state.sale_success = False
if 'last_invoice_text' not in st.session_state:
    st.session_state.last_invoice_text = ""

# --- 2. اتصال قاعدة البيانات ---
class DBHandler:
    def __init__(self):
        self.use_sqlite = False
        self.conn = None
        try:
            if "postgres" in st.secrets:
                self.conn = psycopg2.connect(**st.secrets["postgres"])
            else:
                raise Exception("No secrets found")
        except Exception:
            self.use_sqlite = True
            db_path = 'boutique.db'
            # Check if current dir is writable, fallback to temp if not
            if not os.access('.', os.W_OK):
                db_path = os.path.join(tempfile.gettempdir(), 'boutique.db')
            self.conn = sqlite3.connect(db_path, check_same_thread=False)

    def get_conn(self):
        return self.conn

    def execute(self, query, params=None):
        if self.use_sqlite:
            query = query.replace("public.", "")
            query = query.replace("%s", "?")

        cursor = self.conn.cursor()
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        return cursor

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def read_sql(self, query, params=None):
        if self.use_sqlite:
            query = query.replace("public.", "")
            query = query.replace("%s", "?")
        return pd.read_sql(query, self.conn, params=params)

@st.cache_resource
def get_db():
    return DBHandler()

db = get_db()
conn = db.get_conn() # For raw access if needed, but better use db methods

# دالة لتهيئة الجداول
def init_db():
    try:
        # SQLite needs simpler types sometimes, but TEXT/REAL/INTEGER are fine
        serial = "INTEGER PRIMARY KEY AUTOINCREMENT" if db.use_sqlite else "SERIAL PRIMARY KEY"

        c = db.conn.cursor()
        try:
            # Variants
            q = f"""CREATE TABLE IF NOT EXISTS variants (
                id {serial}, name TEXT, color TEXT, size TEXT, cost REAL, price REAL, stock INTEGER
            )"""
            c.execute(q)

            # Customers
            q = f"""CREATE TABLE IF NOT EXISTS customers (
                id {serial}, name TEXT, phone TEXT, address TEXT, username TEXT
            )"""
            c.execute(q)

            # Sales
            q = f"""CREATE TABLE IF NOT EXISTS sales (
                id {serial}, customer_id INTEGER, variant_id INTEGER, product_name TEXT,
                qty INTEGER, total REAL, profit REAL, date TEXT, invoice_id TEXT
            )"""
            c.execute(q)
            db.commit()
        finally:
            c.close()
    except Exception as e:
        db.rollback()
        st.error(f"DB Init Error: {e}")

init_db()

# --- 3. النوافذ المنبثقة ---
@st.dialog("تعديل عملية بيع")
def edit_sale_dialog(sale_id, current_qty, current_total, variant_id, product_name):
    st.warning(f"فاتورة: {product_name}")
    new_qty = st.number_input("الكمية", min_value=1, value=int(current_qty))
    new_total = st.number_input("الإجمالي", value=float(current_total))
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 حفظ", type="primary"):
            try:
                diff = new_qty - int(current_qty)
                if diff != 0:
                    db.execute("UPDATE public.variants SET stock = stock - %s WHERE id = %s", (int(diff), int(variant_id)))
                db.execute("UPDATE public.sales SET qty = %s, total = %s WHERE id = %s", (int(new_qty), float(new_total), int(sale_id)))
                db.commit(); st.rerun()
            except Exception as e: db.rollback(); st.error(e)
    with c2:
        if st.button("🗑️ حذف"):
            try:
                db.execute("UPDATE public.variants SET stock = stock + %s WHERE id = %s", (int(current_qty), int(variant_id)))
                db.execute("DELETE FROM public.sales WHERE id = %s", (int(sale_id),))
                db.commit(); st.rerun()
            except Exception as e: db.rollback(); st.error(e)

@st.dialog("تعديل المخزون")
def edit_stock_dialog(item_id, name, color, size, cost, price, stock):
    with st.form("edit_stk"):
        n_name = st.text_input("الاسم", value=name)
        c1, c2 = st.columns(2)
        n_col = c1.text_input("اللون", value=color)
        n_siz = c2.text_input("القياس", value=size)
        c3, c4, c5 = st.columns(3)
        n_cst = c3.number_input("كلفة", value=float(cost))
        n_prc = c4.number_input("بيع", value=float(price))
        n_stk = c5.number_input("عدد", value=int(stock))
        if st.form_submit_button("💾 حفظ"):
            try:
                db.execute("UPDATE public.variants SET name=%s, color=%s, size=%s, cost=%s, price=%s, stock=%s WHERE id=%s",
                             (n_name, n_col, n_siz, float(n_cst), float(n_prc), int(n_stk), int(item_id)))
                db.commit(); st.rerun()
            except Exception as e: db.rollback(); st.error(e)
    if st.button("🗑️ حذف نهائي"):
        try:
            db.execute("DELETE FROM public.variants WHERE id=%s", (int(item_id),))
            db.commit(); st.rerun()
        except Exception as e: db.rollback(); st.error(e)

# --- 4. تسجيل الدخول ---
def login_screen():
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.markdown("<h1 style='text-align: center; color: #E91E63;'>🌸 نواعم بوتيك</h1>", unsafe_allow_html=True)
        st.markdown("<div style='text-align: center;'>مرحباً بك في نظام الإدارة</div><br>", unsafe_allow_html=True)

        with st.container(border=True):
            user = st.text_input("اسم المستخدم", placeholder="admin")
            pw = st.text_input("كلمة المرور", type="password", placeholder="••••••")
            if st.button("دخول للنظام", type="primary"):
                if user == "admin" and pw == "admin":
                    st.session_state.logged_in = True
                    st.rerun()
                else:
                    st.error("خطأ في اسم المستخدم أو كلمة المرور")

# --- 5. التطبيق الرئيسي ---
def main_app():
    # Sidebar Navigation
    with st.sidebar:
        st.title("🌸 نواعم")
        page = st.radio("القائمة الرئيسية", ["🛒 نقطة البيع", "📦 إدارة المخزون", "📋 سجل المبيعات", "👥 العملاء", "📊 التقارير"], index=0)
        st.divider()
        st.caption(f"تاريخ: {get_baghdad_time().strftime('%Y-%m-%d')}")
        if st.button("تسجيل خروج"):
            st.session_state.logged_in = False
            st.rerun()

    # === 1. البيع ===
    if page == "🛒 نقطة البيع":
        st.header("🛒 نقطة البيع")
        if st.session_state.sale_success:
            st.success("✅ تم حجز الطلب بنجاح!")
            st.balloons()
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("### 📋 فاتورة للنسخ:")
                st.text_area("نص الفاتورة", st.session_state.last_invoice_text, height=200)
            with c2:
                 if st.button("🔄 عملية بيع جديدة", type="primary", use_container_width=True):
                    st.session_state.sale_success = False; st.session_state.last_invoice_text = ""; st.rerun()
        else:
            col_prod, col_cart = st.columns([2, 1])

            with col_prod:
                st.subheader("بحث عن منتج")
                try:
                    df = db.read_sql("SELECT * FROM public.variants WHERE stock > 0")
                except: df = pd.DataFrame()

                srch = st.text_input("🔍 ابحث باسم المنتج أو اللون...", label_visibility="collapsed")
                if srch and not df.empty:
                    mask = df['name'].str.contains(srch, case=False) | df['color'].str.contains(srch, case=False)
                    df = df[mask]

                if not df.empty:
                    # Grid View for products could be nice, but stick to list for now to ensure speed
                    for i, r in df.iterrows():
                        with st.container(border=True):
                            c1, c2, c3 = st.columns([3, 2, 2])
                            c1.markdown(f"**{r['name']}**")
                            c1.caption(f"{r['color']} | {r['size']}")
                            c2.markdown(f"💰 **{r['price']:,.0f}**")
                            c2.caption(f"متوفر: {r['stock']}")

                            if c3.button("أضف ➕", key=f"add_{r['id']}"):
                                item_dict = {
                                    "id": int(r['id']),
                                    "name": r['name'],
                                    "color": r['color'],
                                    "size": r['size'],
                                    "cost": float(r['cost']),
                                    "price": float(r['price']),
                                    "qty": 1,
                                    "total": float(r['price'])
                                }
                                # Check if already in cart
                                found = False
                                for item in st.session_state.cart:
                                    if item['id'] == r['id']:
                                        item['qty'] += 1
                                        item['total'] = item['qty'] * item['price']
                                        found = True
                                        break
                                if not found:
                                    st.session_state.cart.append(item_dict)
                                st.toast(f"تمت إضافة {r['name']}", icon="✅")
                                st.rerun()

            with col_cart:
                st.subheader("🛒 السلة")
                if st.session_state.cart:
                    for i, item in enumerate(st.session_state.cart):
                        with st.container(border=True):
                            st.markdown(f"**{item['name']}** ({item['size']})")
                            c1, c2 = st.columns(2)
                            new_q = c1.number_input("العدد", 1, 100, item['qty'], key=f"q_{i}")
                            c2.markdown(f"{item['price']*new_q:,.0f}")

                            # Update qty logic
                            if new_q != item['qty']:
                                item['qty'] = new_q
                                item['total'] = item['qty'] * item['price']
                                st.rerun()

                            if st.button("❌", key=f"del_{i}"):
                                st.session_state.cart.pop(i)
                                st.rerun()

                    st.divider()
                    tot = sum(x['total'] for x in st.session_state.cart)
                    st.markdown(f"### الإجمالي: {tot:,.0f} د.ع")

                    with st.expander("بيانات العميل", expanded=True):
                        cust_type = st.radio("نوع العميل", ["جديد", "سابق"], horizontal=True)
                        cust_id_val, cust_name_val = None, ""
                        c_n, c_p, c_a = "", "", ""

                        if cust_type == "سابق":
                            try:
                                curr_custs = db.read_sql("SELECT id, name, phone FROM public.customers")
                            except: curr_custs = pd.DataFrame()

                            if not curr_custs.empty:
                                c_sel = st.selectbox("اختر عميل:", curr_custs.apply(lambda x: f"{x['name']} - {x['phone']}", axis=1).tolist())
                                cust_name_val = c_sel.split(" - ")[0]
                                cust_id_val = int(curr_custs[curr_custs['name'] == cust_name_val]['id'].iloc[0])
                            else: st.warning("لا يوجد عملاء")
                        else:
                            c_n = st.text_input("الاسم")
                            c_p = st.text_input("الهاتف")
                            c_a = st.text_input("العنوان")
                            cust_name_val = c_n

                    if st.button("✅ إتمام البيع", type="primary", use_container_width=True):
                        if not cust_name_val: st.error("الاسم مطلوب!"); st.stop()

                        try:
                            if cust_type == "جديد":
                                cur = db.execute("INSERT INTO public.customers (name, phone, address) VALUES (%s,%s,%s) RETURNING id", (c_n, c_p, c_a))
                                cust_id_val = cur.fetchone()[0]

                            baghdad_now = get_baghdad_time()
                            inv = baghdad_now.strftime("%Y%m%d%H%M")
                            dt = baghdad_now.strftime("%Y-%m-%d %H:%M")

                            invoice_msg = "تم حجز الطلب ✅\n"
                            for x in st.session_state.cart:
                                db.execute("UPDATE public.variants SET stock=stock-%s WHERE id=%s", (int(x['qty']), int(x['id'])))
                                profit_calc = (x['price'] - x['cost']) * x['qty']
                                db.execute("""
                                    INSERT INTO public.sales (customer_id, variant_id, product_name, qty, total, profit, date, invoice_id)
                                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                                """, (int(cust_id_val), int(x['id']), x['name'], int(x['qty']), float(x['total']), float(profit_calc), dt, inv))

                                invoice_msg += f"{x['name']}\n{x['color']}\n{x['size']}\n"
                                if len(st.session_state.cart) > 1: invoice_msg += "---\n"

                            invoice_msg += f"{tot:,.0f}\nالتوصيل مجاني\nالف عافية حياتي 🌸🌸🌸🌸"

                            db.commit()
                            st.session_state.cart = []
                            st.session_state.sale_success = True
                            st.session_state.last_invoice_text = invoice_msg
                            st.rerun()
                        except Exception as e:
                            db.rollback()
                            st.error(f"حدث خطأ: {e}")
                else:
                    st.info("السلة فارغة")

    # === 2. السجل ===
    elif page == "📋 سجل المبيعات":
        st.header("📋 سجل المبيعات")
        try:
            df_s = db.read_sql("SELECT s.*, c.name as customer_name FROM public.sales s LEFT JOIN public.customers c ON s.customer_id = c.id ORDER BY s.id DESC LIMIT 50")

            # Use dataframe with config for better UI
            st.dataframe(
                df_s[['id', 'product_name', 'qty', 'total', 'customer_name', 'date']],
                column_config={
                    "total": st.column_config.NumberColumn("السعر", format="%d د.ع"),
                    "qty": "العدد",
                    "product_name": "المنتج",
                    "customer_name": "العميل",
                    "date": "التاريخ",
                    "id": "رقم"
                },
                use_container_width=True,
                hide_index=True
            )

            st.markdown("### تعديل العمليات")
            for i, r in df_s.iterrows():
                with st.expander(f"{r['product_name']} - {r['customer_name']} ({r['date']})"):
                     c1, c2 = st.columns([4,1])
                     if st.button("تعديل / حذف", key=f"e{r['id']}"):
                         edit_sale_dialog(r['id'], r['qty'], r['total'], r['variant_id'], r['product_name'])
        except Exception as e: st.info(f"لا توجد مبيعات بعد or error: {e}")

    # === 3. العملاء ===
    elif page == "👥 العملاء":
        st.header("👥 قاعدة بيانات العملاء")
        try:
            df_cust = db.read_sql("SELECT * FROM public.customers ORDER BY id DESC")
            if not df_cust.empty:
                st.dataframe(df_cust, use_container_width=True, hide_index=True)
            else: st.info("لا يوجد عملاء")
        except: st.info("فارغ")

    # === 4. المخزون ===
    elif page == "📦 إدارة المخزون":
        st.header("📦 المخزون")

        tab1, tab2 = st.tabs(["قائمة المنتجات", "إضافة منتج جديد"])

        with tab1:
            try:
                df_inv = db.read_sql("SELECT * FROM public.variants WHERE stock > 0 ORDER BY name")
                if not df_inv.empty:
                    st.dataframe(
                        df_inv,
                        column_config={
                            "price": st.column_config.NumberColumn("سعر البيع", format="%d"),
                            "cost": st.column_config.NumberColumn("التكلفة", format="%d"),
                            "stock": "الكمية",
                            "name": "الاسم",
                            "color": "اللون",
                            "size": "القياس"
                        },
                        use_container_width=True,
                        hide_index=True
                    )

                    st.divider()
                    st.subheader("تعديل المنتجات")
                    p_to_edit = st.selectbox("اختر منتج للتعديل", df_inv.apply(lambda x: f"{x['name']} | {x['color']} | {x['size']}", axis=1))
                    if p_to_edit:
                        r = df_inv[df_inv.apply(lambda x: f"{x['name']} | {x['color']} | {x['size']}", axis=1) == p_to_edit].iloc[0]
                        if st.button("تعديل هذا المنتج"):
                             edit_stock_dialog(r['id'], r['name'], r['color'], r['size'], r['cost'], r['price'], r['stock'])

                else: st.info("المخزون فارغ")
            except Exception as e: st.error(str(e))

        with tab2:
            st.subheader("إضافة مخزون")
            with st.form("add"):
                c1, c2 = st.columns(2)
                nm = c1.text_input("اسم المنتج")
                stk = c2.number_input("العدد المتوفر", 1)

                c3, c4 = st.columns(2)
                cl = c3.text_input("ألوان (افصل بفاصلة ،)")
                sz = c4.text_input("قياسات (افصل بفاصلة ،)")

                c5, c6 = st.columns(2)
                pr = c5.number_input("سعر البيع", 0.0)
                cst = c6.number_input("سعر التكلفة", 0.0)

                if st.form_submit_button("💾 حفظ في المخزن", type="primary"):
                    try:
                        colors = [c.strip() for c in cl.replace('،',',').split(',') if c.strip()]
                        sizes = [s.strip() for s in sz.replace('،',',').split(',') if s.strip()]

                        count = 0
                        for c in colors:
                            for s in sizes:
                                # 1. التحقق هل القطعة موجودة؟
                                cur = db.execute("SELECT id FROM public.variants WHERE name=%s AND color=%s AND size=%s", (nm, c, s))
                                existing = cur.fetchone()

                                if existing:
                                    # 2. تحديث الموجود
                                    v_id = existing[0]
                                    db.execute("""
                                        UPDATE public.variants
                                        SET stock = stock + %s, price = %s, cost = %s
                                        WHERE id = %s
                                    """, (int(stk), float(pr), float(cst), v_id))
                                else:
                                    # 3. إضافة جديد
                                    db.execute("""
                                        INSERT INTO public.variants (name,color,size,stock,price,cost)
                                        VALUES (%s,%s,%s,%s,%s,%s)
                                    """, (nm, c, s, int(stk), float(pr), float(cst)))
                                count += 1

                        db.commit()
                        st.success(f"تمت معالجة {count} صنف بنجاح")
                    except Exception as e:
                        db.rollback()
                        st.error(f"خطأ: {e}")

    # === 5. التقارير الذكية ===
    elif page == "📊 التقارير":
        st.header("📊 ذكاء الأعمال (BI)")
        try:
            today_baghdad = get_baghdad_time().strftime("%Y-%m-%d")
            df_tdy = db.read_sql(f"SELECT SUM(total), SUM(profit) FROM public.sales WHERE date LIKE '{today_baghdad}%'").iloc[0]

            st.subheader(f"📅 أداء اليوم ({today_baghdad})")
            col_t1, col_t2 = st.columns(2)
            col_t1.metric("مبيعات اليوم", f"{df_tdy[0] or 0:,.0f} د.ع")
            col_t2.metric("أرباح اليوم الصافية", f"{df_tdy[1] or 0:,.0f} د.ع")
            st.markdown("---")

            st.subheader("📦 القيمة المالية للمخزون")
            df_stock_val = db.read_sql("""
                SELECT SUM(stock * cost) as total_cost, SUM(stock * price) as total_revenue FROM public.variants
            """).iloc[0]

            total_cost_stock = df_stock_val['total_cost'] or 0
            total_rev_stock = df_stock_val['total_revenue'] or 0
            potential_profit = total_rev_stock - total_cost_stock

            col_s1, col_s2, col_s3 = st.columns(3)
            col_s1.metric("رأس المال (التكلفة)", f"{total_cost_stock:,.0f} د.ع")
            col_s2.metric("المبيعات المتوقعة", f"{total_rev_stock:,.0f} د.ع")
            col_s3.metric("الربح المتوقع", f"{potential_profit:,.0f} د.ع", delta="مكسب مستقبلي")
            st.markdown("---")

            c_best1, c_best2 = st.columns(2)
            with c_best1:
                st.subheader("🏆 الأكثر مبيعاً")
                df_top_items = db.read_sql("""
                    SELECT product_name as "المنتج", SUM(qty) as "العدد المباع"
                    FROM public.sales GROUP BY product_name ORDER BY SUM(qty) DESC LIMIT 5
                """)
                if not df_top_items.empty: st.dataframe(df_top_items, use_container_width=True, hide_index=True)
                else: st.info("لا توجد بيانات")

            with c_best2:
                st.subheader("🌟 أفضل الزبائن")
                df_top_cust = db.read_sql("""
                    SELECT c.name as "العميل", SUM(s.total) as "مجموع الشراء"
                    FROM public.sales s JOIN public.customers c ON s.customer_id = c.id
                    GROUP BY c.name ORDER BY SUM(s.total) DESC LIMIT 5
                """)
                if not df_top_cust.empty: st.dataframe(df_top_cust, use_container_width=True, hide_index=True)
                else: st.info("لا توجد بيانات")
        except Exception as e:
            st.info(f"البيانات قيد التجميع... {e}")

if __name__ == "__main__":
    if st.session_state.logged_in:
        main_app()
    else:
        login_screen()
