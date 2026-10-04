import streamlit as st
import pandas as pd
import json
import re
import os
from io import BytesIO
from notion_client import Client

st.set_page_config(page_title="틱톡 라이브 실시간 주문 정산 시스템", layout="wide")

PRODUCTS_FILE = "products.json"

def load_products():
    if os.path.exists(PRODUCTS_FILE):
        with open(PRODUCTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {str(i): {"name": f"상품 {i}번", "price": 10000} for i in range(1, 41)}

def save_products(products):
    with open(PRODUCTS_FILE, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)

if "products" not in st.session_state:
    st.session_state.products = load_products()

if "orders" not in st.session_state:
    st.session_state.orders = []

if "last_added_count" not in st.session_state:
    st.session_state.last_added_count = 0

with st.sidebar:
    st.header("⚙️ 시스템 설정")
    if st.button("🔴 전체 주문 내역 초기화 (새 방송 시작)", type="secondary", use_container_width=True):
        st.session_state.orders = []
        st.session_state.last_added_count = 0
        st.success("모든 주문 내역이 초기화되었습니다.")
        st.rerun()

    st.divider()

    with st.expander("📦 상품 마스터 관리 (1~40번)", expanded=False):
        for i in range(1, 41):
            key_str = str(i)
            p_data = st.session_state.products.get(key_str, {"name": f"상품 {i}번", "price": 0})
            c1, c2 = st.columns([2, 1])
            new_name = c1.text_input(f"{i}번 이름", value=p_data["name"], key=f"p_name_{i}")
            new_price = c2.number_input(f"{i}번 단가", value=int(p_data["price"]), step=1000, key=f"p_price_{i}")
            st.session_state.products[key_str] = {"name": new_name, "price": new_price}
        
        if st.button("상품 데이터 저장", use_container_width=True):
            save_products(st.session_state.products)
            st.success("상품 마스터 데이터가 저장되었습니다.")

    st.divider()
    st.header("🔗 노션(Notion) 연동 설정")
    notion_enabled = st.checkbox("노션 DB 자동 업로드 활성화")
    notion_key = st.text_input("Notion API Key", type="password")
    notion_db_id = st.text_input("Notion Database ID")

st.title("🛍 틱톡 라이브 실시간 주문 정산 시스템")

col1, col2 = st.columns([1, 1.3])

with col1:
    st.subheader("📥 실시간 주문 입력 (누적 방식)")
    
    with st.form(key="order_form", clear_on_submit=True):
        raw_text = st.text_area(
            "주문 텍스트 입력 (1명 또는 여러 명 연속 입력)", 
            height=160, 
            placeholder="예시:\n강상일 3*12 7*1\n홍길동 1, 2~20@\n김철수 3번 2개"
        )
        
        f_col1, f_col2 = st.columns([2, 1])
        submitted = f_col1.form_submit_button("➕ 주문 추가 (Ctrl + Enter)", type="primary", use_container_width=True)
        
        if submitted and raw_text.strip():
            lines = raw_text.strip().split("\n")
            added_count = 0
            for line in lines:
                if not line.strip():
                    continue
                parts = line.strip().split(maxsplit=1)
                nickname = parts[0].strip()
                items_str = parts[1] if len(parts) > 1 else ""
                
                pattern = re.findall(r'(\d+)(?:[~*\-번\s]+(\d+))?@?', items_str)
                
                for item_num, qty in pattern:
                    if item_num:
                        p_num = int(item_num)
                        p_qty = int(qty) if qty else 1
                        
                        num_str = str(p_num)
                        if num_str in st.session_state.products:
                            p_info = st.session_state.products[num_str]
                            p_name = p_info["name"]
                            p_price = p_info["price"]
                        else:
                            p_name = "존재하지 않는 상품 번호"
                            p_price = 0
                            
                        st.session_state.orders.append({
                            "nickname": nickname,
                            "item_num": p_num,
                            "name": p_name,
                            "price": p_price,
                            "qty": p_qty,
                            "total_price": p_price * p_qty
                        })
                        added_count += 1
            st.session_state.last_added_count = added_count
            st.success(f"{added_count}건의 주문 항목이 누적되었습니다.")

    u_col1, u_col2 = st.columns([1, 1])
    with u_col1:
        if st.button("↩️ 직전 입력 취소 (Undo)", use_container_width=True):
            if st.session_state.last_added_count > 0 and len(st.session_state.orders) >= st.session_state.last_added_count:
                del st.session_state.orders[-st.session_state.last_added_count:]
                cancelled = st.session_state.last_added_count
                st.session_state.last_added_count = 0
                st.success(f"최근 추가된 {cancelled}건의 주문이 취소되었습니다.")
                st.rerun()
            else:
                st.warning("취소할 수 있는 직전 입력 내역이 없습니다.")
    with u_col2:
        if st.button("🧹 전체 목록 새로고침", use_container_width=True):
            st.rerun()

    st.divider()
    
    st.subheader("💬 카카오톡 전송용 청구서 생성")
    
    search_nick = st.text_input("🔍 특정 고객 닉네임 검색 (검색 시에만 해당 고객 정산 및 계좌번호 출력)", placeholder="예: 미린")
    is_searching = bool(search_nick.strip())
    
    summary_text = ""
    if st.session_state.orders:
        temp_df = pd.DataFrame(st.session_state.orders)
        
        if not is_searching:
            summary_text += "====================\n"
            summary_text += "[실시간 전체 주문 집계 현황]\n"
            summary_text += f"총 주문 개수: {temp_df['qty'].sum():,}개\n"
            summary_text += f"총 합산 금액: {temp_df['total_price'].sum():,}원\n"
            summary_text += "====================\n\n"
            
            user_groups = temp_df.groupby("nickname", sort=False)
            for name, group in user_groups:
                summary_text += f"[{name} 님]\n"
                user_total_qty = 0
                user_grand_total = 0
                for _, r in group.iterrows():
                    summary_text += f"- {r['item_num']}번 {r['name']} x {r['qty']}개 : {r['total_price']:,}원\n"
                    user_total_qty += r['qty']
                    user_grand_total += r['total_price']
                summary_text += f"▶ 합계: 수량 {user_total_qty:,}개 / 금액 {user_grand_total:,}원\n\n"
        else:
            query_str = search_nick.strip().lower()
            matched_df = temp_df[temp_df["nickname"].astype(str).str.lower().str.contains(query_str)]
            
            if not matched_df.empty:
                user_groups = matched_df.groupby("nickname", sort=False)
                for name, group in user_groups:
                    summary_text += f"[{name} 님 주문 정산 청구서]\n"
                    user_total_qty = 0
                    user_grand_total = 0
                    for _, r in group.iterrows():
                        summary_text += f"- {r['item_num']}번 {r['name']} x {r['qty']}개 : {r['total_price']:,}원\n"
                        user_total_qty += r['qty']
                        user_grand_total += r['total_price']
                    summary_text += f"\n▶ 총 주문 수량: {user_total_qty:,}개\n"
                    summary_text += f"▶ 총 입금액: {user_grand_total:,}원\n\n"
                    summary_text += "계좌번호: 농협 356-0562-4008-43 (경해경)\n"
                    summary_text += "구매 진심으로 감사합니다❤️^^\n\n"
            else:
                summary_text = f"'{search_nick.strip()}'에 해당하는 주문 내역이 없습니다."
    else:
        summary_text = "등록된 주문 내역이 없습니다."
    
    st.session_state["kakao_text_area"] = summary_text
    st.text_area("카톡 복사용", height=260, key="kakao_text_area")

with col2:
    st.subheader("📊 전체 구매 고객 정산 현황 (실시간 감시)")
    
    if st.session_state.orders:
        df_orders = pd.DataFrame(st.session_state.orders)
        
        def refresh_info(row):
            num_str = str(row["item_num"])
            if num_str in st.session_state.products:
                info = st.session_state.products[num_str]
                price = info["price"]
                name = info["name"]
                is_valid = True
            else:
                price = row.get("price", 0)
                name = row.get("name", "존재하지 않는 상품 번호")
                is_valid = False
            return pd.Series([name, price, price * row["qty"], is_valid])

        df_orders[["name", "price", "total_price", "is_valid"]] = df_orders.apply(refresh_info, axis=1)
        
        invalid_orders = df_orders[~df_orders["is_valid"]]
        if not invalid_orders.empty:
            st.error("⚠️ 40번 초과/잘못된 상품 번호 감지:")
            st.dataframe(invalid_orders[["nickname", "item_num", "qty"]], use_container_width=True)
        
        edited_df = st.data_editor(
            df_orders[["nickname", "item_num", "name", "price", "qty", "total_price"]],
            num_rows="dynamic",
            use_container_width=True,
            height=760,
            key="order_editor"
        )
        
        synced_orders = []
        for _, row in edited_df.iterrows():
            if pd.notna(row["nickname"]) and pd.notna(row["item_num"]):
                p_num = int(row["item_num"])
                p_qty = int(row["qty"]) if pd.notna(row["qty"]) else 1
                p_price = int(row["price"]) if pd.notna(row["price"]) else 0
                p_name = str(row["name"]) if pd.notna(row["name"]) else ""
                
                synced_orders.append({
                    "nickname": str(row["nickname"]).strip(),
                    "item_num": p_num,
                    "name": p_name,
                    "price": p_price,
                    "qty": p_qty,
                    "total_price": p_price * p_qty
                })
        st.session_state.orders = synced_orders

        total_customers = edited_df["nickname"].nunique() if not edited_df.empty else 0
        total_quantity = edited_df["qty"].sum() if not edited_df.empty else 0
        total_amount = edited_df["total_price"].sum() if not edited_df.empty else 0

        m1, m2, m3 = st.columns(3)
        m1.metric("총 고객 수", f"{total_customers}명")
        m2.metric("실시간 총 주문 개수", f"{total_quantity:,}개")
        m3.metric("실시간 총 합산 금액", f"{total_amount:,}원")
        
        st.divider()
        
        ex_col1, ex_col2 = st.columns([1, 1])
        with ex_col1:
            excel_buffer = BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                edited_df.to_excel(writer, index=False, sheet_name='전체주문정산내역')
            excel_data = excel_buffer.getvalue()
            
            st.download_button(
                label="📥 출고용 전체 엑셀(.xlsx) 다운로드",
                data=excel_data,
                file_name="tiktok_live_all_orders.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        
        with ex_col2:
            if notion_enabled and notion_key and notion_db_id:
                if st.button("🚀 노션 DB로 일괄 전송", use_container_width=True):
                    try:
                        notion = Client(auth=notion_key)
                        for _, r in edited_df.iterrows():
                            notion.pages.create(
                                parent={"database_id": notion_db_id},
                                properties={
                                    "고객명": {"title": [{"text": {"content": str(r["nickname"])}}]},
                                    "상품번호": {"number": int(r["item_num"])},
                                    "상품명": {"rich_text": [{"text": {"content": str(r["name"])}}]},
                                    "수량": {"number": int(r["qty"])},
                                    "총금액": {"number": int(r["total_price"])}
                                }
                            )
                        st.success("노션 DB 전송 완료!")
                    except Exception as e:
                        st.error(f"노션 업로드 파일 업로드 실패: {e}")
