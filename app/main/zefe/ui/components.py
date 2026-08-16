from __future__ import annotations

import json
from typing import Optional

from fasthtml.common import (
    A,
    Button,
    Div,
    H1,
    H2,
    H3,
    Img,
    Input,
    Label,
    Option,
    P,
    Script,
    Select,
    Span,
    Table,
    Tbody,
    Thead,
    Tr,
    Th,
)

from ui.icons import icon


def alert(kind: str, message: str, cls: str = "mb-5") -> Div:
    palette = {
        "error": ("alert-circle", "bg-rose-50 border-rose-200 text-rose-700"),
        "success": (
            "check-circle",
            "bg-emerald-50 border-emerald-200 text-emerald-700",
        ),
        "warning": (
            "alert-triangle",
            "bg-amber-50 border-amber-200 text-amber-700",
        ),
        "info": ("alert-circle", "bg-sky-50 border-sky-200 text-sky-700"),
    }
    icon_name, palette_cls = palette.get(kind, palette["info"])
    return Div(
        icon(icon_name, cls="h-4 w-4 shrink-0"),
        Span(message, cls="text-sm"),
        cls=f"flex items-center gap-2 px-3 py-2 rounded-lg border {palette_cls} {cls}".strip(),
        role="alert",
    )


def card(*children, cls: str = "") -> Div:
    return Div(
        *children,
        cls=f"bg-white border border-slate-200 rounded-xl p-6 {cls}".strip(),
    )


def section_header(title: str, subtitle: Optional[str] = None) -> Div:
    children = [
        H1(title, cls="text-2xl font-bold text-slate-900 tracking-tight")
    ]
    if subtitle:
        children.append(P(subtitle, cls="text-sm text-slate-500 mt-1"))
    return Div(*children, cls="mb-6")


def primary_button(
    label: str,
    *,
    type: str = "submit",
    icon_name: Optional[str] = None,
    cls: Optional[str] = None,
    **kwargs,
) -> Button:
    inner = []
    if icon_name:
        inner.append(icon(icon_name, cls="h-4 w-4"))
    inner.append(Span(label))
    merged_cls = (
        cls
        if cls is not None
        else (
            "inline-flex items-center justify-center gap-2 px-4 py-2.5 "
            "bg-indigo-600 text-white font-medium text-sm rounded-lg "
            "hover:bg-indigo-700 focus:outline-none focus:ring-2 "
            "focus:ring-indigo-500 focus:ring-offset-1 disabled:opacity-50 "
            "disabled:cursor-not-allowed transition-all active:scale-[0.99]"
        )
    )
    return Button(
        *inner,
        type=type,
        cls=merged_cls,
        **kwargs,
    )


def secondary_button(
    label: str,
    *,
    type: str = "button",
    icon_name: Optional[str] = None,
    cls: Optional[str] = None,
    **kwargs,
) -> Button:
    inner = []
    if icon_name:
        inner.append(icon(icon_name, cls="h-4 w-4"))
    inner.append(Span(label))
    merged_cls = (
        cls
        if cls is not None
        else (
            "inline-flex items-center justify-center gap-2 px-4 py-2 "
            "bg-white border border-slate-300 text-slate-700 font-medium "
            "text-sm rounded-lg hover:bg-slate-50 focus:outline-none "
            "focus:ring-2 focus:ring-indigo-500 transition-all"
        )
    )
    return Button(
        *inner,
        type=type,
        cls=merged_cls,
        **kwargs,
    )


def text_field(
    *,
    name: str,
    label: str,
    type: str = "text",
    placeholder: str = "",
    value: str = "",
    required: bool = False,
    helper: Optional[str] = None,
    autocomplete: Optional[str] = None,
    hide_asterisk: bool = False,
) -> Div:
    input_attrs = {
        "id": name,
        "name": name,
        "type": type,
        "placeholder": placeholder,
        "value": value,
    }
    if required:
        input_attrs["required"] = True
    if autocomplete:
        input_attrs["autocomplete"] = autocomplete
    label_children = [label]
    if required and not hide_asterisk:
        label_children.append(Span(" *", cls="text-rose-500 font-bold"))
    children = [
        Label(
            *label_children,
            fr=name,
            cls="block text-sm font-medium text-slate-700 mb-1.5",
        ),
        Input(
            **input_attrs,
            cls=(
                "w-full px-3 py-2 bg-white text-slate-900 border border-slate-300 "
                "rounded-lg text-sm placeholder-slate-400 focus:outline-none "
                "focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition"
            ),
        ),
    ]
    if helper:
        children.append(P(helper, cls="text-xs text-slate-500 mt-1"))
    return Div(*children, cls="mb-4")


def link(label: str, href: str, **kwargs) -> A:
    return A(
        label,
        href=href,
        cls="text-indigo-600 hover:text-indigo-700 font-medium hover:underline",
        **kwargs,
    )


def guidance_text(text: str, cls: str = "") -> P:
    return P(
        text,
        cls=f"text-[11px] text-slate-500 mt-1.5 leading-relaxed {cls}".strip(),
    )


def guidance_panel(
    text: str,
    title: Optional[str] = None,
    icon_name: str = "info",
    cls: str = "",
) -> Div:
    inner = [
        icon(icon_name, cls="h-3.5 w-3.5 text-indigo-500 shrink-0 mt-0.5"),
        Div(
            P(
                title,
                cls="text-[11px] font-bold text-slate-700 leading-tight mb-0.5",
            )
            if title
            else "",
            P(text, cls="text-[11px] text-slate-600 leading-relaxed"),
            cls="flex-1 min-w-0",
        ),
    ]
    return Div(
        *inner,
        cls=f"flex items-start gap-2.5 p-3 bg-slate-50/80 rounded-xl border border-slate-200 mt-2 {cls}".strip(),
        role="note",
    )


def normalize_country_options(raw) -> list[tuple[str, str]]:
    if not raw:
        return []
    out: list[tuple[str, str]] = []
    for c in raw:
        if isinstance(c, dict):
            code = (c.get("alpha_2") or c.get("code") or "").strip()
            name = (c.get("name") or "").strip()
            if code:
                out.append((code, name or code))
        elif isinstance(c, (list, tuple)) and len(c) >= 2:
            code = str(c[0] or "").strip()
            name = str(c[1] or "").strip()
            if code:
                out.append((code, name or code))
    return out


def normalize_state_options(raw) -> list[tuple[str, str]]:
    if not raw:
        return []
    out: list[tuple[str, str]] = []
    for s in raw:
        if isinstance(s, dict):
            name = (s.get("name") or s.get("code") or "").strip()
            if name:
                out.append((name, name))
        elif isinstance(s, (list, tuple)) and len(s) >= 2:
            label = (str(s[1]) or str(s[0])).strip()
            if label:
                out.append((label, label))
    return out


def country_state_fields(
    *,
    country_value: str = "NG",
    state_value: str = "",
    countries: list | None = None,
    ng_states: list | None = None,
    country_name: str = "country",
    state_name: str = "state",
    required: bool = True,
    field_id_prefix: str = "addr",
    span_full: bool = True,
) -> Div:
    countries = normalize_country_options(countries)
    ng_states = normalize_state_options(ng_states)

    has_choice = len(countries) > 1 or (
        len(countries) == 1 and countries[0][0] != "NG"
    )
    only_ng = not has_choice
    country_value = country_value or "NG"

    chev_cls = (
        "h-4 w-4 text-slate-400 absolute right-3 top-1/2 "
        "-translate-y-1/2 pointer-events-none"
    )
    select_cls = (
        "w-full appearance-none px-3 py-2 pr-9 bg-white text-slate-900 "
        "border border-slate-300 rounded-lg text-sm focus:outline-none "
        "focus:ring-2 focus:ring-indigo-500"
    )
    input_cls = (
        "w-full px-3 py-2 bg-white text-slate-900 border border-slate-300 "
        "rounded-lg text-sm placeholder-slate-400 focus:outline-none "
        "focus:ring-2 focus:ring-indigo-500"
    )

    country_label_children = ["Country"]
    if required:
        country_label_children.append(Span(" *", cls="text-rose-500 font-bold"))

    state_label_children = ["State"]
    if required:
        state_label_children.append(Span(" *", cls="text-rose-500 font-bold"))

    def _ng_state_select(
        *, sid: str, value: str, disabled: bool = False, hidden: bool = False
    ) -> Div:
        opts = [
            Option(
                "Select a state",
                value="",
                disabled=True,
                selected=not value,
            )
        ]
        for code, name in ng_states:
            opts.append(Option(name, value=code, selected=(code == value)))
        select_attrs = {
            "id": sid,
            "name": state_name,
        }
        if required and not disabled:
            select_attrs["required"] = True
        if disabled:
            select_attrs["disabled"] = True
        return Div(
            Select(*opts, **select_attrs, cls=select_cls),
            icon("chevron-down", cls=chev_cls),
            cls="relative",
            id=f"{sid}_wrap",
            style="display:none;" if hidden else "",
        )

    if only_ng:
        country_block = Div(
            Label(
                *country_label_children,
                cls="block text-sm font-medium text-slate-700 mb-1.5",
            ),
            Div(
                Span("🇳🇬", cls="text-base leading-none"),
                Span(
                    "Nigeria",
                    cls="text-sm font-medium text-slate-900",
                ),
                Span(
                    "NG",
                    cls=(
                        "ml-auto text-[11px] font-mono font-semibold "
                        "text-slate-600 bg-slate-100 px-2 py-0.5 rounded"
                    ),
                ),
                cls=(
                    "flex items-center gap-2 px-3 py-2 bg-slate-50 "
                    "border border-slate-200 rounded-lg"
                ),
            ),
            Input(type="hidden", name=country_name, value="NG"),
            cls="mb-4",
        )
        sid = f"{field_id_prefix}_state_select"
        state_block = Div(
            Label(
                *state_label_children,
                fr=sid,
                cls="block text-sm font-medium text-slate-700 mb-1.5",
            ),
            _ng_state_select(sid=sid, value=state_value),
            P(
                "Select your state.",
                cls="text-xs text-slate-500 mt-1",
            ),
            cls="mb-4",
        )
        outer_cls = "grid grid-cols-1 md:grid-cols-2 gap-x-4"
        if span_full:
            outer_cls = f"md:col-span-2 {outer_cls}"
        return Div(country_block, state_block, cls=outer_cls)

    country_select_id = f"{field_id_prefix}_country"
    state_select_id = f"{field_id_prefix}_state_select"
    state_input_id = f"{field_id_prefix}_state_input"

    country_opts = [
        Option(
            "Select country",
            value="",
            disabled=True,
            selected=not country_value,
        )
    ]
    for code, name in countries:
        country_opts.append(
            Option(name, value=code, selected=(code == country_value))
        )

    is_ng = country_value == "NG"

    country_block = Div(
        Label(
            *country_label_children,
            fr=country_select_id,
            cls="block text-sm font-medium text-slate-700 mb-1.5",
        ),
        Div(
            Select(
                *country_opts,
                id=country_select_id,
                name=country_name,
                required=required,
                cls=select_cls,
            ),
            icon("chevron-down", cls=chev_cls),
            cls="relative",
        ),
        cls="mb-4",
    )

    ng_select = _ng_state_select(
        sid=state_select_id,
        value=state_value if is_ng else "",
        disabled=not is_ng,
        hidden=not is_ng,
    )
    text_input_attrs = {
        "id": state_input_id,
        "name": state_name,
        "type": "text",
        "placeholder": "State / province / region",
        "value": state_value if not is_ng else "",
    }
    if not is_ng and required:
        text_input_attrs["required"] = True
    if is_ng:
        text_input_attrs["disabled"] = True
    text_input = Div(
        Input(**text_input_attrs, cls=input_cls),
        cls="relative",
        id=f"{state_input_id}_wrap",
        style="display:none;" if is_ng else "",
    )

    state_block = Div(
        Label(
            *state_label_children,
            cls="block text-sm font-medium text-slate-700 mb-1.5",
        ),
        ng_select,
        text_input,
        P(
            "Select a state for Nigeria, or type the state for others.",
            cls="text-xs text-slate-500 mt-1",
        ),
        cls="mb-4",
    )

    js_required = "true" if required else "false"
    js = (
        "(function(){"
        f"var COUNTRY_ID={json.dumps(country_select_id)};"
        f"var DD_WRAP_ID={json.dumps(state_select_id + '_wrap')};"
        f"var DD_ID={json.dumps(state_select_id)};"
        f"var TX_WRAP_ID={json.dumps(state_input_id + '_wrap')};"
        f"var TX_ID={json.dumps(state_input_id)};"
        f"var REQ={js_required};"
        "function $(id){return document.getElementById(id);}"
        "function sync(){"
        "var sel=$(COUNTRY_ID);if(!sel)return;"
        "var ddw=$(DD_WRAP_ID),dd=$(DD_ID),txw=$(TX_WRAP_ID),tx=$(TX_ID);"
        "var ng=(sel.value==='NG');"
        "if(ddw){ddw.style.display=ng?'':'none';}"
        "if(dd){dd.disabled=!ng;if(REQ)dd.required=ng;}"
        "if(txw){txw.style.display=ng?'none':'';}"
        "if(tx){tx.disabled=ng;if(REQ)tx.required=!ng;"
        "if(ng){tx.value='';}}"
        "}"
        "var s=$(COUNTRY_ID);"
        "if(s){s.addEventListener('change',sync);sync();}"
        "})();"
    )

    outer_cls = "grid grid-cols-1 md:grid-cols-2 gap-x-4"
    if span_full:
        outer_cls = f"md:col-span-2 {outer_cls}"
    return Div(country_block, state_block, Script(js), cls=outer_cls)


def pagination_controls(
    page: int,
    total_pages: int,
    q: str,
    base_path: str,
    target_id: str,
) -> Div:
    from fasthtml.common import Button as _Button

    prev_page = page - 1
    next_page = page + 1
    btn_cls = (
        "relative inline-flex items-center px-4 py-2 border border-slate-300 "
        "text-sm font-medium rounded-lg text-slate-700 bg-white hover:bg-slate-50 "
        "disabled:opacity-50 disabled:cursor-not-allowed"
    )

    prev_attrs = {"cls": btn_cls, "type": "button"}
    if page <= 1:
        prev_attrs["disabled"] = "true"
    else:
        prev_attrs["hx-get"] = f"{base_path}?page={prev_page}&q={q}"
        prev_attrs["hx-target"] = target_id
        prev_attrs["hx-swap"] = "innerHTML"
        prev_attrs["hx-push-url"] = "true"

    next_attrs = {"cls": btn_cls, "type": "button"}
    if page >= total_pages:
        next_attrs["disabled"] = "true"
    else:
        next_attrs["hx-get"] = f"{base_path}?page={next_page}&q={q}"
        next_attrs["hx-target"] = target_id
        next_attrs["hx-swap"] = "innerHTML"
        next_attrs["hx-push-url"] = "true"

    return Div(
        Div(
            P(
                "Page ",
                Span(page, cls="font-semibold text-slate-900"),
                " of ",
                Span(total_pages, cls="font-semibold text-slate-900"),
                cls="text-sm text-slate-700",
            ),
            cls="flex-1 flex items-center justify-between sm:hidden",
        ),
        Div(
            Div(
                _Button(
                    icon("arrow-left", cls="h-4 w-4 mr-2"),
                    Span("Previous"),
                    **prev_attrs,
                ),
                Span(
                    f"Page {page} of {total_pages}",
                    cls="text-sm text-slate-600 font-medium px-4",
                ),
                _Button(
                    Span("Next"),
                    icon("arrow-right", cls="h-4 w-4 ml-2"),
                    **next_attrs,
                ),
                cls="flex items-center justify-between w-full sm:justify-end gap-3",
            ),
            cls="hidden sm:flex-1 sm:flex sm:items-center sm:justify-between",
        ),
        cls=(
            "bg-white px-4 py-3 flex items-center justify-between border-t "
            "border-slate-200 sm:px-6 mt-4 rounded-xl border border-slate-200"
        ),
    )


def auth_card(title: str, subtitle: str, icon_name: str, *children) -> Div:
    return Div(
        Div(
            Div(
                Img(
                    src="/static/img/icon_purple.svg",
                    alt="Zetamind",
                    cls="h-12 w-12",
                ),
                cls="flex items-center justify-center mx-auto mb-2",
            ),
            H2(
                title,
                cls="text-2xl font-bold text-slate-900 text-center tracking-tight",
            ),
            P(subtitle, cls="text-sm text-slate-500 text-center mt-1 mb-5"),
            *children,
            cls="bg-white border border-slate-200 rounded-2xl p-8 w-full max-w-md shadow-sm",
        ),
        cls="min-h-screen flex items-center justify-center bg-slate-50 p-4",
    )


def icon_button(
    icon_name: str, title: str, variant: str = "default", **kwargs
) -> Button:
    variants = {
        "default": "text-slate-500 hover:bg-slate-100 hover:text-indigo-600",
        "danger": "text-slate-400 hover:bg-rose-50 hover:text-rose-600",
        "primary": "text-white bg-indigo-600 hover:bg-indigo-700",
    }
    cls = f"p-2 rounded-lg transition-colors {variants.get(variant, variants['default'])}"
    return Button(
        icon(icon_name, cls="h-4 w-4"), title=title, cls=cls, **kwargs
    )


def modal_shell(
    title: str, subtitle: str, content, footer=None, id: str = None
) -> Div:
    header = Div(
        Div(
            H2(title, cls="text-xl font-bold text-slate-900"),
            P(subtitle, cls="text-sm text-slate-500 mt-0.5"),
            cls="flex-1",
        ),
        Button(
            icon("x", cls="h-4 w-4"),
            hx_get="/customers/clear-overlay",
            hx_target="#customer-modal-area",
            cls="p-1.5 rounded-lg text-slate-400 hover:bg-slate-100",
        ),
        cls="flex items-start justify-between px-6 py-4 border-b border-slate-200",
    )

    main_content = Div(content, cls="p-6 overflow-y-auto max-h-[70vh]")

    footer_div = (
        Div(
            footer,
            cls="flex justify-end gap-2 px-6 py-4 border-t border-slate-100 bg-slate-50/50 rounded-b-2xl",
        )
        if footer
        else ""
    )

    return Div(
        Div(
            Div(
                header,
                main_content,
                footer_div,
                cls="bg-white border border-slate-200 rounded-2xl w-full max-w-3xl shadow-xl animate-fade-in-up",
            ),
            cls="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 backdrop-blur-xs p-4",
        ),
        id=id,
    )


def confirm_modal(
    title: str,
    message: str,
    confirm_btn,
    cancel_hx_target: str,
    icon_name: str = "alert-triangle",
) -> Div:
    return Div(
        Div(
            Div(
                Div(
                    Div(
                        icon(icon_name, cls="h-6 w-6 text-rose-600"),
                        cls="h-12 w-12 rounded-full bg-rose-100 flex items-center justify-center mb-4 mx-auto",
                    ),
                    H3(
                        title,
                        cls="text-lg font-bold text-slate-950 text-center",
                    ),
                    P(message, cls="text-sm text-slate-600 text-center mt-2"),
                    cls="p-6",
                ),
                Div(
                    Button(
                        Span("Cancel"),
                        hx_get="/customers/clear-overlay",
                        hx_target=cancel_hx_target,
                        type="button",
                        cls="px-4 py-2 bg-white border border-slate-300 text-slate-700 text-sm font-medium rounded-lg hover:bg-slate-50",
                    ),
                    confirm_btn,
                    cls="flex items-center justify-end gap-2 px-6 py-4 border-t border-slate-200 bg-slate-50 rounded-b-2xl",
                ),
                cls="bg-white border border-slate-200 rounded-2xl max-w-md w-full shadow-lg relative z-50 animate-fade-in-up",
            ),
            cls="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 backdrop-blur-xs p-4",
        )
    )


def confirm_dialog(
    *,
    title: str,
    message: str,
    confirm_control,
    cancel_get: str,
    cancel_target: str,
    icon_name: str = "alert-triangle",
    tone: str = "danger",
    details=None,
    cancel_label: str = "Cancel",
    max_w: str = "max-w-md",
) -> Div:
    """Flat, professional confirmation overlay for irreversible decisions.

    ``confirm_control`` is the caller's own form/button that performs the action,
    so each page keeps full control of its route contract.
    """
    tones = {
        "danger": ("bg-rose-100", "text-rose-600"),
        "warning": ("bg-amber-100", "text-amber-600"),
        "info": ("bg-indigo-100", "text-indigo-600"),
        "neutral": ("bg-slate-100", "text-slate-700"),
    }
    bg_cls, icon_cls = tones.get(tone, tones["danger"])
    return Div(
        Div(
            Div(
                Div(
                    icon(icon_name, cls=f"h-6 w-6 {icon_cls}"),
                    cls=(
                        f"h-12 w-12 rounded-full {bg_cls} flex items-center "
                        "justify-center mb-4 mx-auto"
                    ),
                ),
                H3(
                    title,
                    cls="text-lg font-bold text-slate-950 text-center",
                ),
                P(
                    message,
                    cls="text-sm text-slate-600 text-center mt-2 leading-relaxed",
                ),
                details or "",
                cls="p-6",
            ),
            Div(
                Button(
                    Span(cancel_label),
                    type="button",
                    hx_get=cancel_get,
                    hx_target=cancel_target,
                    hx_swap="innerHTML",
                    cls=(
                        "px-4 py-2 bg-white border border-slate-300 "
                        "text-slate-700 text-sm font-medium rounded-lg "
                        "hover:bg-slate-50"
                    ),
                ),
                confirm_control,
                cls=(
                    "flex items-center justify-end gap-2 px-6 py-4 "
                    "border-t border-slate-200 bg-slate-50 rounded-b-2xl"
                ),
            ),
            cls=(
                "bg-white border border-slate-200 rounded-2xl w-full "
                f"{max_w} shadow-lg animate-fade-in-up"
            ),
        ),
        cls=(
            "fixed inset-0 z-50 flex items-center justify-center "
            "bg-slate-900/40 backdrop-blur-xs p-4"
        ),
    )


def confirm_detail_rows(rows: list[tuple[str, str]]) -> Div:
    """Compact label/value summary used inside confirmation dialogs."""
    items = []
    for label, value in rows:
        items.append(
            Div(
                Span(label, cls="text-xs font-semibold text-slate-500"),
                Span(
                    value or "—",
                    cls="text-sm font-medium text-slate-900 text-right truncate",
                ),
                cls="flex items-center justify-between gap-3 min-w-0",
            )
        )
    return Div(
        *items,
        cls=(
            "mt-5 p-4 bg-slate-50 border border-slate-200 rounded-xl "
            "flex flex-col gap-2"
        ),
    )


def table_container(headers: list, rows: list, id: str = None) -> Div:
    thead_cells = [
        Th(
            h,
            cls="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider",
        )
        for h in headers
    ]
    return Div(
        Table(
            Thead(
                Tr(*thead_cells, cls="border-b border-slate-200 bg-slate-50")
            ),
            Tbody(*rows),
            cls="table-auto w-full",
        ),
        cls="overflow-hidden rounded-2xl border border-slate-200 bg-white",
        id=id,
    )


def empty_state(
    icon_name: str, title: str, subtitle: str, action_link=None, id: str = None
) -> Div:
    content = [
        icon(icon_name, cls="h-10 w-10 text-slate-300 mx-auto mb-3"),
        P(title, cls="text-base font-semibold text-slate-900"),
        P(subtitle, cls="text-sm text-slate-500 mt-1"),
    ]
    if action_link:
        content.append(action_link)
    return Div(
        *content,
        cls="text-center py-16 bg-white rounded-2xl border border-slate-200",
        id=id,
    )
