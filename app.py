"""Streamlit UI for the Flying Tiger agent — with product cards."""
import time
import uuid

import streamlit as st

from agent import MODEL, run_agent

st.set_page_config(page_title="Flying Tiger", page_icon="🐯", layout="wide")

st.title("🐯 Flying Tiger Copenhagen")
st.caption("Ask about products, prices, stock, sales — in English, Swedish, or Chinese.")

EXAMPLES = [
    "what's on sale?",
    "christmas decorations under 50 kr",
    "toys for kids",
    "cheapest mugs",
    "home accessories under 100 kr",
    "products with the biggest discount",
    "kitchen items in stock",
    "products under 20 kr",
]

PRODUCT_BASE_URL = "https://flyingtiger.com/products"


# ---------- state ----------
def init_state():
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("pending", None)
    st.session_state.setdefault("show_sql", False)
    st.session_state.setdefault("show_raw", False)


def make_message(role: str, **extra) -> dict:
    return {"id": uuid.uuid4().hex[:8], "role": role, **extra}


def call_agent(prompt: str):
    t0 = time.perf_counter()
    try:
        answer, meta = run_agent(prompt, verbose=False)
    except Exception as e:
        return (
            f"⚠️ Error: `{type(e).__name__}: {e}`",
            {"sql": [], "products": [], "kind": "error", "error": str(e)},
            time.perf_counter() - t0,
        )
    if not isinstance(meta, dict):
        meta = {"sql": [], "products": [], "kind": "empty", "error": None}
    return answer, meta, time.perf_counter() - t0


# ---------- product card ----------
def render_product_card(p: dict) -> None:
    with st.container(border=True):
        col_img, col_body = st.columns([1, 2])

        with col_img:
            url = p.get("image_url")
            if url:
                try:
                    st.image(url, use_container_width=True)
                except Exception:
                    st.caption("(image unavailable)")
            else:
                st.caption("(no image)")

        with col_body:
            title = p.get("name", "(no title)")
            handle = p.get("handle")
            if handle:
                link = f"{PRODUCT_BASE_URL}/{handle}"
                st.markdown(f"**[{title}]({link})**")
            else:
                st.markdown(f"**{title}**")

            price = p.get("price")
            compare = p.get("compare_at_price")
            on_sale = p.get("on_sale")

            if price is not None:
                if on_sale and compare and compare > price:
                    pct = int(100 * (1 - price / compare))
                    st.markdown(
                        f"### {price:.2f}  "
                        f"~~{compare:.2f}~~  :red[**−{pct}%**]"
                    )
                else:
                    st.markdown(f"### {price:.2f}")

            bits = []
            if p.get("available") is False:
                bits.append("⚠️ out of stock")
            elif p.get("available") is True:
                bits.append("✅ in stock")
            if p.get("grams"):
                bits.append(f"{p['grams']:.0f} g")
            if p.get("id"):
                bits.append(f"`{p['id']}`")
            if bits:
                st.caption(" · ".join(bits))


def render_products(products: list[dict]) -> None:
    """3-column grid of product cards."""
    if not products:
        return
    cols = st.columns(3)
    for i, p in enumerate(products):
        with cols[i % 3]:
            render_product_card(p)


# ---------- sidebar ----------
def render_sidebar():
    with st.sidebar:
        st.header("Try these")
        for ex in EXAMPLES:
            if st.button(ex, use_container_width=True, key=f"ex__{ex}"):
                st.session_state.pending = ex
        st.divider()
        st.caption(f"Model: `{MODEL}`")
        st.toggle("Show SQL", key="show_sql")
        st.toggle("Show raw text", key="show_raw",
                  help="Show the model's prose alongside product cards")
        if st.button("Clear chat", use_container_width=True):
            st.session_state.messages = []
            st.rerun()


# ---------- message rendering ----------
def render_assistant_body(msg: dict):
    products = msg.get("products") or []
    content = msg.get("content", "")

    if products:
        if st.session_state.show_raw and content:
            st.markdown(content)
        render_products(products)
    else:
        st.markdown(content)


def render_message(m: dict):
    with st.chat_message(m["role"]):
        if m["role"] == "user":
            st.markdown(m["content"])
            return

        render_assistant_body(m)

        if m.get("error"):
            st.caption(f"⚠️ `{m['error']}`")

        if st.session_state.show_sql and m.get("sql"):
            with st.expander(f"🔧 SQL ({len(m['sql'])})", expanded=False):
                for q in m["sql"]:
                    st.code(q, language="sql")

        if m.get("elapsed") is not None:
            st.caption(f"⏱ {m['elapsed']:.2f}s")


# ---------- main ----------
def main():
    init_state()
    render_sidebar()

    for m in st.session_state.messages:
        render_message(m)

    typed = st.chat_input("Ask something...")

    prompt = None
    if st.session_state.pending:
        prompt = st.session_state.pending
        st.session_state.pending = None
    elif typed:
        prompt = typed

    if not prompt:
        return

    user_msg = make_message("user", content=prompt)
    st.session_state.messages.append(user_msg)
    render_message(user_msg)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            answer, meta, elapsed = call_agent(prompt)

        assistant_msg = make_message(
            "assistant",
            content=answer,
            products=meta.get("products", []),
            sql=meta.get("sql", []),
            error=meta.get("error"),
            elapsed=elapsed,
        )
        st.session_state.messages.append(assistant_msg)
        render_message(assistant_msg)


if __name__ == "__main__":
    main()