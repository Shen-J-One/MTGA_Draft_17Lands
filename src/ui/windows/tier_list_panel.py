import tkinter
import threading
from tkinter import ttk, messagebox
import os
from datetime import datetime
from typing import Callable

from src.i18n import t
from src.tier_list import TierList, TIER_FOLDER, TIER_FILE_PREFIX, TIER_URL_17LANDS
from src.ui.styles import Theme
from src.ui.components import DynamicTreeviewManager


class TierListWindow(ttk.Frame):
    def __init__(self, parent, configuration, on_update_callback: Callable):
        super().__init__(parent)
        self.configuration = configuration
        self.on_update_callback = on_update_callback
        self.vars = {}
        self._import_thread = None
        self._build_ui()
        self.refresh()

    def refresh(self):
        self._update_history_table()

    def _build_ui(self):
        container = ttk.Frame(self, padding=Theme.scaled_val(10))
        container.pack(fill="both", expand=True)

        # --- 1. MANAGEMENT BAR ---
        top_bar = ttk.Frame(container)
        top_bar.pack(fill="x", pady=Theme.scaled_val((0, 5)))

        ttk.Label(
            top_bar, text=t("tier.section_imported"), bootstyle="secondary"
        ).pack(side="left")

        self.btn_delete = ttk.Button(
            top_bar,
            text=t("tier.btn_delete_selected"),
            bootstyle="danger-outline",
            command=self._delete_selected,
        )
        self.btn_delete.pack(side="right", padx=Theme.scaled_val((5, 0)))

        self.var_filter = tkinter.StringVar(value=t("tier.filter_all_sets"))
        self.combo_filter = ttk.Combobox(
            top_bar, textvariable=self.var_filter, state="readonly", width=12
        )
        self.combo_filter.pack(side="right")
        self.combo_filter.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        ttk.Label(top_bar, text=t("tier.filter_label"), bootstyle="secondary").pack(
            side="right", padx=Theme.scaled_val(5)
        )

        # --- 2. HISTORY TABLE ---
        self.table_manager = DynamicTreeviewManager(
            container,
            view_id="tier_list_history",
            configuration=self.configuration,
            on_update_callback=self.refresh,
            static_columns=["Set", "Label", "Date"],
            height=4,
        )
        self.table_manager.pack(
            fill="both", expand=True, pady=Theme.scaled_val((0, 15))
        )
        self.table = self.table_manager.tree

        # --- 3. IMPORT FORM ---
        form_frame = ttk.Frame(
            container, style="Card.TFrame", padding=Theme.scaled_val(15)
        )
        form_frame.pack(fill="x")
        ttk.Label(
            form_frame,
            text=t("tier.section_import"),
            font=Theme.scaled_font(9, "bold"),
            bootstyle="primary",
        ).pack(anchor="w", pady=Theme.scaled_val((0, 10)))
        ttk.Label(form_frame, text=t("tier.label_url"), bootstyle="secondary").pack(
            anchor="w"
        )
        self.vars["url"] = tkinter.StringVar(
            value="https://www.17lands.com/tier_list/..."
        )
        self.entry_url = ttk.Entry(form_frame, textvariable=self.vars["url"])
        self.entry_url.pack(fill="x", pady=Theme.scaled_val((2, 10)))
        ttk.Label(
            form_frame, text=t("tier.label_custom"), bootstyle="secondary"
        ).pack(anchor="w")
        self.vars["label"] = tkinter.StringVar()
        self.entry_label = ttk.Entry(form_frame, textvariable=self.vars["label"])
        self.entry_label.pack(fill="x", pady=Theme.scaled_val((2, 15)))
        self.btn_import = ttk.Button(
            form_frame, text=t("tier.btn_import"), command=self._start_import
        )
        self.btn_import.pack(fill="x")
        self.vars["status"] = tkinter.StringVar(value=t("topbar.ready"))
        ttk.Label(
            form_frame, textvariable=self.vars["status"], bootstyle="secondary"
        ).pack(pady=Theme.scaled_val((5, 0)))

    def _update_history_table(self):
        for item in self.table.get_children():
            self.table.delete(item)

        # Get all files using the internal cache method to populate filter options
        all_files = TierList._get_all_files()
        sets = sorted(list(set([f[0] for f in all_files])))

        all_sets_label = t("tier.filter_all_sets")
        current_filter = self.var_filter.get()
        self.combo_filter["values"] = [all_sets_label] + sets
        if current_filter not in [all_sets_label] + sets:
            self.var_filter.set(all_sets_label)
            current_filter = all_sets_label

        filtered_files = []
        for f_set, f_label, f_date, f_name, _ in all_files:
            if current_filter != all_sets_label and f_set != current_filter:
                continue
            filtered_files.append((f_set, f_label, f_date, f_name))

        filtered_files.sort(key=lambda x: x[2], reverse=True)

        for idx, f in enumerate(filtered_files):
            tag = "bw_odd" if idx % 2 == 0 else "bw_even"
            self.table.insert(
                "", "end", iid=f[3], values=(f[0], f[1], f[2]), tags=(tag,)
            )

    def _delete_selected(self):
        selection = self.table.selection()
        if not selection:
            return

        if messagebox.askyesno(
            t("tier.confirm_delete_title"),
            t("tier.confirm_delete_body"),
        ):
            for item_id in selection:
                TierList.delete_file(item_id)

            self.refresh()
            if self.on_update_callback:
                self.on_update_callback()

    def _start_import(self):
        url, label = self.vars["url"].get().strip(), self.vars["label"].get().strip()
        if not url.startswith(TIER_URL_17LANDS):
            messagebox.showwarning(
                t("tier.invalid_url_title"), t("tier.invalid_url_body")
            )
            return
        if not label:
            messagebox.showwarning(
                t("tier.missing_label_title"), t("tier.missing_label_body")
            )
            return

        self.btn_import.configure(state="disabled")
        self.vars["status"].set(t("tier.status_connecting"))

        self._import_thread = threading.Thread(
            target=self._run_import, args=(url, label), daemon=True
        )
        self._import_thread.start()

    def _run_import(self, url, label):
        try:
            new_tl = TierList.from_api(url)
            if self.winfo_exists():
                if new_tl:
                    new_tl.meta.label = label
                    filename = f"{TIER_FILE_PREFIX}_{new_tl.meta.set}_{int(datetime.now().timestamp())}.txt"
                    new_tl.to_file(os.path.join(TIER_FOLDER, filename))
                    self._safe_finalize()
                else:
                    self._safe_error(t("tier.api_error"))
        except Exception as e:
            self._safe_error(str(e))

    def _safe_finalize(self):
        def callback():
            if hasattr(self, "winfo_exists") and self.winfo_exists():
                self._finalize_import()

        if threading.current_thread() is threading.main_thread():
            callback()
        else:
            try:
                self.after(0, callback)
            except RuntimeError:
                pass  # Safely ignore during headless test execution

    def _safe_error(self, err):
        def callback():
            if hasattr(self, "winfo_exists") and self.winfo_exists():
                self._handle_error(err)

        if threading.current_thread() is threading.main_thread():
            callback()
        else:
            try:
                self.after(0, callback)
            except RuntimeError:
                pass  # Safely ignore during headless test execution

    def _finalize_import(self):
        self.btn_import.configure(state="normal")
        self._update_history_table()
        self.vars["url"].set("https://www.17lands.com/tier_list/...")
        self.vars["label"].set("")
        self.vars["status"].set(t("tier.status_success"))
        if self.on_update_callback:
            self.on_update_callback()

    def _handle_error(self, err):
        self.btn_import.configure(state="normal")
        self.vars["status"].set(t("tier.status_failed"))
        messagebox.showerror(t("tier.import_error_title"), err)
