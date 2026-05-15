"""
src/ui/windows/settings.py
Professional Configuration UI for the MTGA Draft Tool.
Streamlined for Tactical Intelligence and Layered Styling.
"""

import os
import tkinter
from tkinter import ttk, messagebox, filedialog
from typing import Callable, Dict, List, Tuple

from src import constants, i18n
from src.i18n import t
from src.configuration import Configuration, reset_configuration, write_configuration
from src.ui.styles import Theme
from src.ui.components import identify_safe_coordinates


class SettingsWindow(tkinter.Toplevel):
    def __init__(
        self, parent, configuration: Configuration, on_update_callback: Callable
    ):
        super().__init__(parent)
        self.configuration = configuration
        self.on_update_callback = on_update_callback

        self.title(t("settings.title"))
        self.resizable(False, False)
        self.transient(parent)  # Keeps window on top of main app

        self.vars: Dict[str, tkinter.Variable] = {}
        self.trace_ids: List[Tuple[tkinter.Variable, str]] = []

        self._build_ui()
        self._load_settings()

        # Center and Focus
        self.update_idletasks()
        x, y = identify_safe_coordinates(
            parent, self.winfo_width(), self.winfo_height(), 50, 50
        )
        self.geometry(f"+{x}+{y}")
        if self.configuration.settings.always_on_top:
            self.attributes("-topmost", True)
        self.grab_set()  # Modal interaction

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        container = ttk.Frame(self, padding=Theme.scaled_val(20))
        container.pack(fill="both", expand=True)

        # --- SECTION: LANGUAGE ---
        ttk.Label(
            container, text="LANGUAGE / 语言", font=Theme.scaled_font(9, "bold")
        ).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=Theme.scaled_val((0, 10))
        )

        ttk.Label(container, text="Display Language:").grid(
            row=1, column=0, sticky="e", padx=Theme.scaled_val(5)
        )
        self.vars["language"] = tkinter.StringVar()  # stores code: "zh_CN" / "en"
        self._lang_display_var = tkinter.StringVar()  # stores label shown in dropdown
        self._lang_display_to_code = {v: k for k, v in i18n.LANGUAGE_DISPLAY.items()}
        lang_combo = ttk.Combobox(
            container,
            textvariable=self._lang_display_var,
            values=list(i18n.LANGUAGE_DISPLAY.values()),
            state="readonly",
        )
        lang_combo.grid(row=1, column=1, sticky="ew", pady=Theme.scaled_val(2))

        # Mirror display label -> internal code on every change.
        self._lang_display_var.trace_add(
            "write",
            lambda *_: self.vars["language"].set(
                self._lang_display_to_code.get(
                    self._lang_display_var.get(), self.vars["language"].get()
                )
            ),
        )

        ttk.Label(
            container,
            text="(Restart required / 需重启生效)",
            font=Theme.scaled_font(8, "italic"),
            foreground="gray",
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=Theme.scaled_val(5))

        # --- SECTION: DATA FORMAT ---
        ttk.Label(
            container, text=t("settings.section_data"), font=Theme.scaled_font(9, "bold")
        ).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=Theme.scaled_val((15, 10))
        )

        ttk.Label(container, text=t("settings.win_rate_format")).grid(
            row=4, column=0, sticky="e", padx=Theme.scaled_val(5)
        )
        self.vars["result_format"] = tkinter.StringVar()
        fmt_om = ttk.OptionMenu(
            container,
            self.vars["result_format"],
            "",
            *constants.RESULT_FORMAT_LIST,
            style="TMenubutton",
        )
        fmt_om.grid(row=4, column=1, sticky="ew", pady=Theme.scaled_val(2))

        ttk.Label(container, text=t("settings.deck_filter_format")).grid(
            row=5, column=0, sticky="e", padx=Theme.scaled_val(5)
        )
        self.vars["filter_format"] = tkinter.StringVar()
        filter_om = ttk.OptionMenu(
            container,
            self.vars["filter_format"],
            "",
            *constants.DECK_FILTER_FORMAT_LIST,
            style="TMenubutton",
        )
        filter_om.grid(row=5, column=1, sticky="ew", pady=Theme.scaled_val(2))

        ttk.Label(container, text=t("settings.ui_scale")).grid(
            row=6, column=0, sticky="e", padx=Theme.scaled_val(5)
        )
        self.vars["ui_size"] = tkinter.StringVar()

        # Sort options nicely (80%, 90%, 100%, etc.)
        size_options = sorted(
            constants.UI_SIZE_DICT.keys(), key=lambda x: int(x.replace("%", ""))
        )
        size_om = ttk.OptionMenu(
            container,
            self.vars["ui_size"],
            "",
            *size_options,
            style="TMenubutton",
        )
        size_om.grid(row=6, column=1, sticky="ew", pady=Theme.scaled_val(2))

        # --- SECTION: ADVISOR & HUD ---
        r = 7
        ttk.Label(
            container,
            text=t("settings.section_intelligence"),
            font=Theme.scaled_font(9, "bold"),
        ).grid(
            row=r, column=0, columnspan=2, sticky="w", pady=Theme.scaled_val((20, 10))
        )

        features = [
            (t("settings.always_on_top"), "always_on_top"),
            (t("settings.auto_sync_datasets"), "auto_sync_datasets"),
            (t("settings.highlight_row_mana"), "card_colors_enabled"),
            (t("settings.check_dataset_updates"), "update_notifications_enabled"),
            (t("settings.alert_missing_datasets"), "missing_notifications_enabled"),
            (t("settings.enable_draft_log"), "draft_log_enabled"),
        ]

        for i, (label, key) in enumerate(features):
            var = tkinter.IntVar()
            self.vars[key] = var
            ttk.Checkbutton(container, text=label, variable=var).grid(
                row=r + 1 + i,
                column=0,
                columnspan=2,
                sticky="w",
                padx=Theme.scaled_val(10),
                pady=Theme.scaled_val(2),
            )

        r += len(features) + 1

        # --- SECTION: SYSTEM PATHS ---
        ttk.Label(
            container,
            text=t("settings.section_paths"),
            font=Theme.scaled_font(9, "bold"),
        ).grid(
            row=r, column=0, columnspan=2, sticky="w", pady=Theme.scaled_val((20, 10))
        )
        r += 1

        ttk.Label(container, text=t("settings.player_log_location")).grid(
            row=r, column=0, sticky="e", padx=Theme.scaled_val(5)
        )
        self.vars["arena_log_location"] = tkinter.StringVar()
        ttk.Entry(
            container, textvariable=self.vars["arena_log_location"], width=40
        ).grid(row=r, column=1, sticky="w", pady=Theme.scaled_val(2))
        r += 1

        ttk.Label(container, text=t("settings.mtga_data_location")).grid(
            row=r, column=0, sticky="e", padx=Theme.scaled_val(5)
        )
        self.vars["database_location"] = tkinter.StringVar()
        ttk.Entry(
            container, textvariable=self.vars["database_location"], width=40
        ).grid(row=r, column=1, sticky="w", pady=Theme.scaled_val(2))
        r += 1

        # --- FOOTER ---
        footer = ttk.Frame(container)
        footer.grid(
            row=50, column=0, columnspan=2, pady=Theme.scaled_val((25, 0)), sticky="ew"
        )

        ttk.Button(
            footer, text=t("settings.restore_defaults"), command=self._reset_defaults
        ).pack(side="left")
        ttk.Button(footer, text=t("settings.done"), command=self._on_close).pack(
            side="right"
        )

    def _load_settings(self):
        """Populates UI from the configuration object."""
        s = self.configuration.settings
        self._toggle_traces(False)

        # Standard settings
        self.original_ui_size = s.ui_size
        self.vars["result_format"].set(s.result_format)
        self.vars["filter_format"].set(s.filter_format)
        self.vars["ui_size"].set(self.original_ui_size)

        # Language: load code into vars["language"] and display label into the combo
        self.vars["language"].set(s.language)
        self._lang_display_var.set(
            i18n.LANGUAGE_DISPLAY.get(s.language, i18n.LANGUAGE_DISPLAY[i18n.DEFAULT_LANG])
        )

        # Paths
        self.vars["arena_log_location"].set(s.arena_log_location)
        self.vars["database_location"].set(s.database_location)

        # Checkbox logic
        checkbox_keys = [
            "always_on_top",
            "auto_sync_datasets",
            "card_colors_enabled",
            "update_notifications_enabled",
            "missing_notifications_enabled",
            "draft_log_enabled",
        ]

        for key in checkbox_keys:
            val = getattr(s, key)
            self.vars[key].set(int(val))

        self._toggle_traces(True)

    def _toggle_traces(self, enable: bool):
        """Standard trace management to prevent save-loops during loading."""
        if enable:
            for k, v in self.vars.items():
                tid = v.trace_add(
                    "write", lambda *a, key=k: self._on_setting_changed(key)
                )
                self.trace_ids.append((v, tid))
        else:
            for var, tid in self.trace_ids:
                try:
                    var.trace_remove("write", tid)
                except:
                    pass
            self.trace_ids.clear()

    def _on_setting_changed(self, key: str):
        """Persists single change and notifies the main application."""
        val = self.vars[key].get()

        # Handle type conversion
        if isinstance(val, int) and key != "result_format":
            bool_val = bool(val)
            setattr(self.configuration.settings, key, bool_val)
            val = bool_val
        else:
            setattr(self.configuration.settings, key, val)

        write_configuration(self.configuration)

        # Keep the settings window on top of the main window if toggled
        if key == "always_on_top":
            self.attributes("-topmost", val)

        # Immediate visual update if something was toggled
        if self.on_update_callback:
            try:
                self.on_update_callback(key)
            except TypeError:
                self.on_update_callback()

    def _reset_defaults(self):
        """Restores pro-level baseline configuration."""
        if messagebox.askyesno(
            t("settings.confirm_reset_title"), t("settings.confirm_reset_body")
        ):
            reset_configuration()
            from src.configuration import read_configuration

            new_conf, _ = read_configuration()
            self.configuration.settings = new_conf.settings
            self._load_settings()
            if self.on_update_callback:
                try:
                    self.on_update_callback(None)
                except TypeError:
                    self.on_update_callback()

    def _on_close(self):
        self._toggle_traces(False)
        self.destroy()
